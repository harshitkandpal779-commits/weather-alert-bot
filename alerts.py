"""
Alert engine for the Advanced Weather Alert Bot.

Turns raw weather data into structured alerts:

  * Extreme heat / cold (temp AND feels-like)
  * Rain / snow expected today or tomorrow (chance + mm thresholds)
  * High winds & dangerous gusts
  * Poor visibility (fog / smog)
  * Very high UV index
  * Air-quality alert (US EPA AQI above threshold, e.g. Delhi smog)
  * Pressure extremes
  * Official government weather alerts passed through from WeatherAPI

Features: severity levels, human advice per alert, and a persistent
cooldown/dedup store so the same alert is not emailed repeatedly.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import config
from weather import CurrentWeather, ForecastDay, WeatherAlert

log = logging.getLogger("alerts")

# Severity ordering (also drives emoji + email colour)
SEV_INFO = "INFO"
SEV_WARNING = "WARNING"
SEV_SEVERE = "SEVERE"

_SEV_EMOJI = {SEV_INFO: "ℹ️", SEV_WARNING: "⚠️", SEV_SEVERE: "🚨"}
_SEV_RANK = {SEV_INFO: 0, SEV_WARNING: 1, SEV_SEVERE: 2}


@dataclass
class Alert:
    city: str
    kind: str          # stable id used for dedup, e.g. "hot", "aqi"
    title: str
    severity: str
    message: str
    advice: str = ""
    timestamp: str = ""

    def key(self) -> str:
        return f"{self.city.lower()}::{self.kind}"

    def emoji(self) -> str:
        return _SEV_EMOJI.get(self.severity, "•")


# ---------------------------------------------------------------------------
# Persistent cooldown store (JSON file)
# ---------------------------------------------------------------------------
def _load_state() -> dict[str, float]:
    try:
        return json.loads(config.STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, float]) -> None:
    try:
        config.STATE_FILE.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        log.error("Could not persist alert state: %s", exc)


def _should_send(alert: Alert, state: dict[str, float]) -> bool:
    last = state.get(alert.key(), 0)
    cooldown = config.ALERT_COOLDOWN_HOURS * 3600
    now = time.time()
    if last and (now - last) < cooldown:
        return False
    return True


# ---------------------------------------------------------------------------
# Advice text per alert type
# ---------------------------------------------------------------------------
_ADVICE = {
    "hot": "Stay hydrated, avoid direct sun between 11:00–16:00, and never leave people or pets in parked cars.",
    "cold": "Dress in warm layers, protect extremities, and check on elderly or vulnerable neighbours.",
    "rain": "Carry an umbrella/raincoat, expect waterlogging, and avoid driving through flooded roads.",
    "snow": "Wear proper footwear, allow extra travel time, and keep your car's fuel tank above half.",
    "wind": "Secure loose objects outdoors, stay away from trees and hoardings, and beware of dust storms.",
    "gust": "Sudden strong gusts — avoid two-wheeler travel and elevated structures if possible.",
    "visibility": "Low visibility: use headlights, keep distance while driving, and wear an N95 mask outdoors.",
    "uv": "High UV: apply SPF-50 sunscreen, wear sunglasses and a cap, limit midday outdoor exposure.",
    "aqi": "Poor air quality: minimise outdoor exercise, wear an N95 mask, and run air purifiers indoors.",
    "pressure": "Unusual pressure often precedes storms — keep weather updates handy.",
    "official": "Follow instructions from local authorities and stay tuned to official advisories.",
}


def _mk(city: str, kind: str, title: str, sev: str, msg: str) -> Alert:
    return Alert(
        city=city, kind=kind, title=title, severity=sev, message=msg,
        advice=_ADVICE.get(kind, ""),
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------
def evaluate_current(city: str, cur: CurrentWeather) -> list[Alert]:
    """Rules that apply to live conditions."""
    out: list[Alert] = []
    disp = cur.location_name or city

    # Heat / cold — use the harsher of actual and feels-like temperature
    t = max(cur.temp_c, cur.feels_like_c)
    tl = min(cur.temp_c, cur.feels_like_c)
    if t >= config.HOT_THRESHOLD + 7:
        out.append(_mk(disp, "hot", "Extreme Heat", SEV_SEVERE,
                       f"Temperature {cur.temp_c:.1f}°C (feels like {cur.feels_like_c:.1f}°C) — dangerously hot."))
    elif t >= config.HOT_THRESHOLD:
        out.append(_mk(disp, "hot", "Heat Alert", SEV_WARNING,
                       f"Temperature {cur.temp_c:.1f}°C (feels like {cur.feels_like_c:.1f}°C) — above {config.HOT_THRESHOLD:g}°C."))
    if tl <= config.COLD_THRESHOLD - 7:
        out.append(_mk(disp, "cold", "Extreme Cold", SEV_SEVERE,
                       f"Temperature {cur.temp_c:.1f}°C (feels like {cur.feels_like_c:.1f}°C) — dangerously cold."))
    elif tl <= config.COLD_THRESHOLD:
        out.append(_mk(disp, "cold", "Cold Alert", SEV_WARNING,
                       f"Temperature {cur.temp_c:.1f}°C (feels like {cur.feels_like_c:.1f}°C) — below {config.COLD_THRESHOLD:g}°C."))

    # Wind & gusts
    if cur.wind_kph >= config.WIND_THRESHOLD_KPH + 25:
        out.append(_mk(disp, "wind", "Damaging Winds", SEV_SEVERE,
                       f"Winds {cur.wind_kph:.0f} km/h from {cur.wind_dir}."))
    elif cur.wind_kph >= config.WIND_THRESHOLD_KPH:
        out.append(_mk(disp, "wind", "High Wind Alert", SEV_WARNING,
                       f"Winds {cur.wind_kph:.0f} km/h from {cur.wind_dir}."))
    if cur.gust_kph >= config.GUST_THRESHOLD_KPH:
        out.append(_mk(disp, "gust", "Strong Gusts", SEV_WARNING,
                       f"Gusts up to {cur.gust_kph:.0f} km/h."))

    # Active precipitation
    if cur.rain_mm > 0 or "rain" in cur.condition.lower():
        if cur.rain_mm >= 5:
            out.append(_mk(disp, "rain", "Heavy Rain Now", SEV_SEVERE,
                           f"Heavy {cur.condition.lower()} with {cur.rain_mm:.1f} mm accumulated."))
    if cur.snow_cm > 0 or "snow" in cur.condition.lower() or "sleet" in cur.condition.lower():
        out.append(_mk(disp, "snow", "Snow Now", SEV_WARNING,
                       f"{cur.condition} — {cur.snow_cm:.1f} cm snowfall."))

    # Visibility
    if cur.visibility_km <= config.VISIBILITY_THRESHOLD_KM:
        sev = SEV_SEVERE if cur.visibility_km < 0.5 else SEV_WARNING
        out.append(_mk(disp, "visibility", "Low Visibility", sev,
                       f"Visibility only {cur.visibility_km:.1f} km ({cur.condition})."))

    # UV
    if cur.uv >= config.UV_THRESHOLD:
        out.append(_mk(disp, "uv", "Very High UV Index", SEV_WARNING,
                       f"UV index {cur.uv:.0f}."))

    # Air quality
    aqi = cur.air_quality.aqi_us
    if aqi >= config.AQI_THRESHOLD + 100:
        out.append(_mk(disp, "aqi", "Hazardous Air Quality", SEV_SEVERE,
                       f"AQI {aqi} ({cur.air_quality.category()}), PM2.5 {cur.air_quality.pm2_5:.0f} µg/m³."))
    elif aqi >= config.AQI_THRESHOLD:
        out.append(_mk(disp, "aqi", "Unhealthy Air Quality", SEV_WARNING,
                       f"AQI {aqi} ({cur.air_quality.category()}), PM2.5 {cur.air_quality.pm2_5:.0f} µg/m³."))

    # Pressure extremes
    if cur.pressure_mb and cur.pressure_mb <= config.PRESSURE_LOW_MB:
        out.append(_mk(disp, "pressure", "Very Low Pressure", SEV_WARNING,
                       f"Pressure {cur.pressure_mb:.0f} mb — storm likely."))
    elif cur.pressure_mb >= config.PRESSURE_HIGH_MB:
        out.append(_mk(disp, "pressure", "Very High Pressure", SEV_INFO,
                       f"Pressure {cur.pressure_mb:.0f} mb."))

    return out


def evaluate_forecast(city: str, days: list[ForecastDay]) -> list[Alert]:
    """Rain/snow/wind/temp rules looking at today and tomorrow."""
    out: list[Alert] = []
    for i, d in enumerate(days[:2]):
        when = "today" if i == 0 else "tomorrow"
        if d.chance_of_rain >= config.RAIN_CHANCE_THRESHOLD + 25:
            out.append(_mk(city, "rain", f"Heavy Rain {when.capitalize()}", SEV_SEVERE,
                           f"{d.date}: {d.chance_of_rain}% rain chance, ~{d.rain_mm:.1f} mm expected."))
        elif d.chance_of_rain >= config.RAIN_CHANCE_THRESHOLD:
            out.append(_mk(city, "rain", f"Rain Expected {when.capitalize()}", SEV_WARNING,
                           f"{d.date}: {d.chance_of_rain}% rain chance, ~{d.rain_mm:.1f} mm expected."))
        if d.chance_of_snow >= config.SNOW_CHANCE_THRESHOLD:
            sev = SEV_WARNING if d.chance_of_snow < 80 else SEV_SEVERE
            out.append(_mk(city, "snow", f"Snow Expected {when.capitalize()}", sev,
                           f"{d.date}: {d.chance_of_snow}% snow chance, ~{d.snow_cm:.1f} cm."))
        if d.max_wind_kph >= config.WIND_THRESHOLD_KPH:
            out.append(_mk(city, "wind", f"High Winds {when.capitalize()}", SEV_WARNING,
                           f"{d.date}: winds up to {d.max_wind_kph:.0f} km/h."))
        if d.max_temp_c >= config.HOT_THRESHOLD + 7:
            out.append(_mk(city, "hot", f"Extreme Heat {when.capitalize()}", SEV_SEVERE,
                           f"{d.date}: high of {d.max_temp_c:.1f}°C expected."))
        if d.min_temp_c <= config.COLD_THRESHOLD - 7:
            out.append(_mk(city, "cold", f"Extreme Cold {when.capitalize()}", SEV_SEVERE,
                           f"{d.date}: low of {d.min_temp_c:.1f}°C expected."))
    return out


def evaluate_official(city: str, alerts: list[WeatherAlert]) -> list[Alert]:
    out: list[Alert] = []
    for a in alerts:
        sev = SEV_SEVERE if a.severity.upper() in ("SEVERE", "EXTREME") else SEV_WARNING
        head = a.headline or a.event
        out.append(_mk(city, "official", f"Official: {a.event}", sev,
                       f"{head}\nEffective: {a.effective} → Expires: {a.expires}"))
    return out


# ---------------------------------------------------------------------------
# Top-level: collect + deduplicate
# ---------------------------------------------------------------------------
def collect_alerts(city: str, cur: CurrentWeather | None,
                   days: list[ForecastDay], official: list[WeatherAlert]) -> list[Alert]:
    """Evaluate every rule set and filter out alerts still inside cooldown."""
    candidates: list[Alert] = []
    if cur:
        candidates += evaluate_current(city, cur)
    candidates += evaluate_forecast(city, days)
    candidates += evaluate_official(city, official)

    state = _load_state()
    fresh: list[Alert] = []
    seen: set[str] = set()
    for alert in sorted(candidates, key=lambda a: -_SEV_RANK.get(a.severity, 0)):
        if alert.key() in seen:
            continue
        seen.add(alert.key())
        if _should_send(alert, state):
            fresh.append(alert)
            state[alert.key()] = time.time()
    _save_state(state)
    return fresh
