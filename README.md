# 🌦 Advanced Weather Alert Bot

A feature-rich Python bot that monitors live weather & air quality for one or
more cities and emails **beautifully formatted HTML alerts and daily briefings**
via Gmail SMTP. Built on [WeatherAPI.com](https://www.weatherapi.com/).

## ✨ Features

- **Multi-city monitoring** — comma-separated list in `CITY`
- **10+ smart alert rules**: heat / cold (incl. feels-like), rain, snow, high
  wind, dangerous gusts, low visibility (fog/smog), very high UV, air-quality
  (AQI + PM2.5), pressure extremes, and **official government weather alerts**
- **Severity levels** — ℹ️ INFO / ⚠️ WARNING / 🚨 SEVERE with colour-coded emails
- **Human advice** attached to every alert (what to do about it)
- **Alert cooldown & dedup** — the same alert is not emailed twice within
  `ALERT_COOLDOWN_HOURS` (state persisted in `alert_state.json`)
- **Daily HTML briefing email** at a configurable hour (current conditions
  table, multi-day forecast, active alerts, personalised tips)
- **Rich console output** — watch the bot work without email
- **Resilience** — retries with exponential backoff, rate-limit handling,
  graceful Ctrl+C shutdown, rotating log files (`weather_bot.log`)
- **Air-quality estimation** — computes US-EPA AQI from raw PM2.5 when your
  API plan doesn't expose the index directly

## 🚀 Quick start

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in your secrets
python main.py test-email   # verify SMTP works
python main.py status       # console weather report (no email)
python main.py check        # one-shot alert check
python main.py run          # continuous monitor (every 30 min by default)
```

## 💻 CLI

| Command | Description |
|---|---|
| `python main.py run` | Continuous monitoring loop (default mode) |
| `python main.py check` | One-shot alert check for all cities |
| `python main.py status` | Console weather report, no emails |
| `python main.py briefing` | Send today's full HTML briefing now |
| `python main.py test-email` | Verify Gmail SMTP settings |
| `python main.py search <name>` | Find valid location names |
| `-v / --verbose` flag | Debug-level logging |

## ⚙️ Configuration (`.env`)

| Key | Default | Meaning |
|---|---|---|
| `API_KEY` | — | WeatherAPI.com key |
| `SENDER_EMAIL` / `SENDER_PASSWORD` | — | Gmail + **app password** |
| `RECEIVER_EMAIL` | — | Where alerts go |
| `CITY` | `New Delhi, India` | Comma-separated monitored places |
| `HOT_THRESHOLD` / `COLD_THRESHOLD` | 35 / 10 | °C alert thresholds |
| `RAIN_CHANCE_THRESHOLD` / `SNOW_CHANCE_THRESHOLD` | 60 / 50 | % chance |
| `WIND_THRESHOLD_KPH` / `GUST_THRESHOLD_KPH` | 40 / 60 | km/h |
| `AQI_THRESHOLD` / `UV_THRESHOLD` / `VISIBILITY_THRESHOLD_KM` | 150 / 8 / 2 | |
| `PRESSURE_LOW_MB` / `PRESSURE_HIGH_MB` | 990 / 1030 | |
| `CHECK_INTERVAL_MINUTES` | 30 | polling frequency |
| `FORECAST_DAYS` | 3 | 1–10 day outlook |
| `ALERT_COOLDOWN_HOURS` | 6 | anti-spam per alert type |
| `DAILY_BRIEFING_HOUR` | 7 | local hour for the briefing |
| `SEND_ALERTS` | true | set false for dry runs |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USE_SSL` | gmail / 587 / false | override for other providers |

## 📁 Project layout

```
main.py       # CLI + scheduler (run/check/status/briefing/test-email/search)
config.py     # all settings, loaded from .env
weather.py    # WeatherAPI client: current, forecast, alerts, AQI, search
alerts.py     # rule engine: severities, advice, cooldown/dedup state
notifier.py   # HTML email builder + Gmail SMTP sender + console rendering
```

## 🔐 Gmail setup

Use a 16-character **App Password** (Google Account → Security → 2-Step
Verification → App passwords), not your normal password. Never commit `.env`
(it is gitignored).

## ⚠️ Note on WeatherAPI plans

The free *explore* key does not include the `/airquality` endpoint; the bot
automatically estimates AQI from the PM2.5 reading instead, so smog alerts
still work.
