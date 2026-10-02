"""
Notification layer for the Advanced Weather Alert Bot.

  * Beautiful HTML emails (alerts, daily briefing, weather report) via Gmail SMTP
  * Retries with backoff on transient SMTP failures
  * Rich console output so you can watch the bot work without email
"""

from __future__ import annotations

import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

import config
from alerts import Alert
from weather import CurrentWeather, ForecastDay, WeatherAlert

log = logging.getLogger("notifier")

_SEV_COLOR = {"INFO": "#1976d2", "WARNING": "#f57c00", "SEVERE": "#d32f2f"}


# ---------------------------------------------------------------------------
# Console rendering
# ---------------------------------------------------------------------------
def _fmt_current(cur: CurrentWeather) -> str:
    aq = cur.air_quality
    lines = [
        f"📍 {cur.location_name}, {cur.country}  ({cur.localtime})",
        f"   🌡 {cur.temp_c:.1f}°C (feels like {cur.feels_like_c:.1f}°C) — {cur.condition}",
        f"   💧 Humidity {cur.humidity}% | 🌬 Wind {cur.wind_kph:.0f} km/h {cur.wind_dir} (gusts {cur.gust_kph:.0f})",
        f"   🔽 Pressure {cur.pressure_mb:.0f} mb | 👁 Visibility {cur.visibility_km:.1f} km | ☀ UV {cur.uv:.0f}",
        f"   😷 AQI {aq.aqi_us} ({aq.category()}) | PM2.5 {aq.pm2_5:.0f} µg/m³",
    ]
    return "\n".join(lines)


def print_console_alerts(alerts: list[Alert]) -> None:
    if not alerts:
        print("✅ No new alerts.")
        return
    print(f"🔔 {len(alerts)} new alert(s):")
    for a in alerts:
        print(f"  {a.emoji()} [{a.severity}] {a.city}: {a.title} — {a.message}")
        if a.advice:
            print(f"      💡 {a.advice}")


def print_console_briefing(city: str, cur: CurrentWeather | None,
                           days: list[ForecastDay], official: list[WeatherAlert]) -> None:
    print("=" * 62)
    print(f"🌦  WEATHER BRIEFING — {city}")
    print("=" * 62)
    if cur:
        print(_fmt_current(cur))
    else:
        print("⚠️ Could not fetch current conditions.")
    if days:
        print("\n📅 Forecast:")
        for d in days:
            icon = "🌧" if d.chance_of_rain >= 50 else ("❄️" if d.chance_of_snow >= 50 else "⛅")
            print(f"   {icon} {d.date}: {d.min_temp_c:.0f}–{d.max_temp_c:.0f}°C, {d.daily_condition}, "
                  f"rain {d.chance_of_rain}% ({d.rain_mm:.1f} mm), wind ≤{d.max_wind_kph:.0f} km/h, UV {d.uv:.0f}")
            print(f"      🌅 {d.sunrise} → 🌇 {d.sunset}")
    if official:
        print("\n🏛 Official alerts:")
        for a in official:
            print(f"   🚨 {a.event} [{a.severity}] — {a.headline}")
    print("=" * 62)


# ---------------------------------------------------------------------------
# Email HTML builders
# ---------------------------------------------------------------------------
def _page(title: str, subtitle: str, body_html: str, accent: str = "#1565c0") -> str:
    return f"""\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#eceff1;font-family:Segoe UI,Arial,sans-serif;">
  <div style="max-width:640px;margin:0 auto;padding:16px;">
    <div style="background:{accent};color:#fff;border-radius:12px 12px 0 0;padding:20px 24px;">
      <h1 style="margin:0;font-size:22px;">{title}</h1>
      <p style="margin:6px 0 0;opacity:.85;font-size:13px;">{subtitle}</p>
    </div>
    <div style="background:#fff;border-radius:0 0 12px 12px;padding:24px;">
      {body_html}
    </div>
    <p style="text-align:center;color:#90a4ae;font-size:11px;margin-top:14px;">
      Sent automatically by your Advanced Weather Alert Bot 🤖
    </p>
  </div>
</body></html>"""


def build_alerts_email(alerts: list[Alert]) -> tuple[str, str]:
    worst = max((a.severity for a in alerts), key=lambda s: {"INFO": 0, "WARNING": 1, "SEVERE": 2}[s])
    subject = {"SEVERE": "🚨 SEVERE ", "WARNING": "⚠️ ", "INFO": ""}[worst] + \
              f"Weather Alert{'s' if len(alerts) > 1 else ''}: " + ", ".join(
                  sorted({a.title.split(' (')[0] for a in alerts}))[:80]

    cards = ""
    for a in alerts:
        color = _SEV_COLOR.get(a.severity, "#1565c0")
        cards += f"""
        <div style="border-left:5px solid {color};background:#fafafa;border-radius:8px;padding:14px 16px;margin-bottom:14px;">
          <div style="font-size:15px;font-weight:700;color:{color};">{a.emoji()} {a.title}
            <span style="float:right;font-size:11px;color:#78909c;">{a.timestamp}</span></div>
          <div style="margin:6px 0;color:#37474f;font-size:14px;"><b>{a.city}</b> — {a.message}</div>
          {f'<div style="font-size:13px;color:#546e7a;">💡 {a.advice}</div>' if a.advice else ''}
        </div>"""
    html = _page("Weather Alerts", f"{len(alerts)} active alert(s)", cards,
                 accent=_SEV_COLOR.get(worst, "#1565c0"))
    return subject, html


def build_briefing_email(city: str, cur: CurrentWeather | None,
                         days: list[ForecastDay], alerts: list[Alert]) -> tuple[str, str]:
    subject = f"🌦 Daily Weather Briefing — {city}"

    now_html = ""
    if cur:
        rows = [
            ("Temperature", f"{cur.temp_c:.1f}°C (feels {cur.feels_like_c:.1f}°C)"),
            ("Conditions", cur.condition),
            ("Humidity", f"{cur.humidity}%"),
            ("Wind", f"{cur.wind_kph:.0f} km/h {cur.wind_dir} (gusts {cur.gust_kph:.0f})"),
            ("Pressure", f"{cur.pressure_mb:.0f} mb"),
            ("Visibility", f"{cur.visibility_km:.1f} km"),
            ("UV Index", f"{cur.uv:.0f}"),
            ("Air Quality", f"AQI {cur.air_quality.aqi_us} — {cur.air_quality.category()} (PM2.5 {cur.air_quality.pm2_5:.0f} µg/m³)"),
        ]
        trs = "".join(
            f'<tr><td style="padding:7px 12px;color:#607d8b;border-bottom:1px solid #eceff1;">{k}</td>'
            f'<td style="padding:7px 12px;font-weight:600;border-bottom:1px solid #eceff1;">{v}</td></tr>'
            for k, v in rows)
        now_html = f"""
        <h2 style="font-size:16px;color:#37474f;margin:0 0 8px;">Current conditions — {cur.location_name} ({cur.localtime})</h2>
        <table style="width:100%;border-collapse:collapse;font-size:14px;color:#263238;margin-bottom:20px;">{trs}</table>"""

    fc_rows = ""
    for d in days:
        fc_rows += f"""
        <tr>
          <td style="padding:8px 10px;border-bottom:1px solid #eceff1;font-weight:600;">{d.date}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eceff1;">{d.min_temp_c:.0f}–{d.max_temp_c:.0f}°C</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eceff1;">{d.daily_condition}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eceff1;">🌧 {d.chance_of_rain}% ({d.rain_mm:.1f} mm)</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eceff1;">💨 {d.max_wind_kph:.0f} km/h</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eceff1;">☀ {d.uv:.0f}</td>
        </tr>"""
    fc_html = f"""
        <h2 style="font-size:16px;color:#37474f;margin:0 0 8px;">Forecast</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px;color:#263238;margin-bottom:20px;">
          <tr style="background:#eceff1;">
            <th style="padding:8px 10px;text-align:left;">Date</th><th style="padding:8px 10px;text-align:left;">Temp</th>
            <th style="padding:8px 10px;text-align:left;">Sky</th><th style="padding:8px 10px;text-align:left;">Rain</th>
            <th style="padding:8px 10px;text-align:left;">Wind</th><th style="padding:8px 10px;text-align:left;">UV</th>
          </tr>{fc_rows}
        </table>""" if days else ""

    alert_html = ""
    if alerts:
        items = "".join(f"<li style='margin:4px 0;'>{a.emoji()} <b>{a.title}</b> — {a.message}</li>" for a in alerts)
        alert_html = f"""
        <h2 style="font-size:16px;color:#c62828;margin:0 0 8px;">Active alerts</h2>
        <ul style="font-size:14px;color:#37474f;margin:0 0 16px;padding-left:20px;">{items}</ul>"""

    advice_html = ""
    if cur:
        tips = []
        if cur.temp_c >= 30:
            tips.append("Stay hydrated and avoid harsh midday sun.")
        if cur.air_quality.aqi_us > 100:
            tips.append("Wear an N95 mask outdoors; keep indoor purifiers running.")
        if any(d.chance_of_rain >= 50 for d in days[:1]):
            tips.append("Carry an umbrella today.")
        if cur.uv >= 6:
            tips.append("Use SPF-50 sunscreen before going out.")
        if cur.visibility_km < 3:
            tips.append("Drive carefully — reduced visibility.")
        if not tips:
            tips.append("Mild conditions — enjoy your day! 🙂")
        advice_html = "<h2 style='font-size:16px;color:#37474f;margin:0 0 8px;'>💡 Today's advice</h2><ul style='font-size:14px;color:#546e7a;margin:0;padding-left:20px;'>" + \
                      "".join(f"<li>{t}</li>" for t in tips) + "</ul>"

    html = _page(f"Weather Briefing — {city}", "Your daily at-a-glance weather report",
                 now_html + fc_html + alert_html + advice_html)
    return subject, html


# ---------------------------------------------------------------------------
# SMTP sending
# ---------------------------------------------------------------------------
def send_email(subject: str, html_body: str, *, retries: int = 3) -> bool:
    """Send an HTML email from SENDER_EMAIL to RECEIVER_EMAIL. Returns success."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.SENDER_EMAIL
    msg["To"] = config.RECEIVER_EMAIL
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    for attempt in range(1, retries + 1):
        try:
            if config.SMTP_USE_SSL:
                server = smtplib.SMTP_SSL(config.SMTP_HOST, 465, timeout=30)
            else:
                server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
                server.ehlo()
                server.starttls()
                server.ehlo()
            with server:
                server.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
                server.sendmail(config.SENDER_EMAIL, config.RECEIVER_EMAIL, msg.as_string())
            log.info("Email sent: %s", subject)
            return True
        except smtplib.SMTPAuthenticationError as exc:
            log.error("SMTP auth failed — check SENDER_EMAIL / app password: %s", exc)
            return False
        except (smtplib.SMTPException, OSError) as exc:
            wait = 2 ** attempt
            log.warning("SMTP error (attempt %d/%d): %s — retrying in %ds", attempt, retries, exc, wait)
            if attempt < retries:
                time.sleep(wait)
    log.error("Failed to send email after %d attempts: %s", retries, subject)
    return False


def notify_alerts(alerts: list[Alert]) -> bool:
    subject, html = build_alerts_email(alerts)
    return send_email(subject, html)


def notify_briefing(city: str, cur: CurrentWeather | None,
                    days: list[ForecastDay], alerts: list[Alert] | None = None) -> bool:
    subject, html = build_briefing_email(city, cur, days, alerts or [])
    return send_email(subject, html)
