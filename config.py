"""
Central configuration for the Advanced Weather Alert Bot.

All tunable values can be overridden through environment variables / .env file.
Secrets (API key, email credentials) are loaded from .env and are never hardcoded.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Secrets / required settings
# ---------------------------------------------------------------------------
API_KEY: str = os.getenv("API_KEY", "")
SENDER_EMAIL: str = os.getenv("SENDER_EMAIL", "")
SENDER_PASSWORD: str = os.getenv("SENDER_PASSWORD", "")
RECEIVER_EMAIL: str = os.getenv("RECEIVER_EMAIL", "")

# Comma-separated list of monitored locations (default: New Delhi, India)
CITY: str = os.getenv("CITY", "New Delhi, India")
CITIES: list[str] = [c.strip() for c in CITY.split(",") if c.strip()]

# ---------------------------------------------------------------------------
# Alert thresholds (in °C unless noted)
# ---------------------------------------------------------------------------
HOT_THRESHOLD: float = float(os.getenv("HOT_THRESHOLD", "35"))
COLD_THRESHOLD: float = float(os.getenv("COLD_THRESHOLD", "10"))
RAIN_CHANCE_THRESHOLD: int = int(os.getenv("RAIN_CHANCE_THRESHOLD", "60"))   # %
SNOW_CHANCE_THRESHOLD: int = int(os.getenv("SNOW_CHANCE_THRESHOLD", "50"))   # %
WIND_THRESHOLD_KPH: float = float(os.getenv("WIND_THRESHOLD_KPH", "40"))     # km/h
AQI_THRESHOLD: int = int(os.getenv("AQI_THRESHOLD", "150"))                  # US EPA AQI
UV_THRESHOLD: int = int(os.getenv("UV_THRESHOLD", "8"))                      # UV index
VISIBILITY_THRESHOLD_KM: float = float(os.getenv("VISIBILITY_THRESHOLD_KM", "2"))
GUST_THRESHOLD_KPH: float = float(os.getenv("GUST_THRESHOLD_KPH", "60"))
PRESSURE_LOW_MB: float = float(os.getenv("PRESSURE_LOW_MB", "990"))
PRESSURE_HIGH_MB: float = float(os.getenv("PRESSURE_HIGH_MB", "1030"))

# ---------------------------------------------------------------------------
# Scheduler / behaviour
# ---------------------------------------------------------------------------
CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))
FORECAST_DAYS: int = int(os.getenv("FORECAST_DAYS", "3"))                    # 1..10 (plan limit)
ALERT_COOLDOWN_HOURS: int = int(os.getenv("ALERT_COOLDOWN_HOURS", "6"))      # per alert type per city
DAILY_BRIEFING_HOUR: int = int(os.getenv("DAILY_BRIEFING_HOUR", "7"))        # local time of first city
SEND_ALERTS: bool = os.getenv("SEND_ALERTS", "true").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Storage / logging
# ---------------------------------------------------------------------------
STATE_FILE: Path = BASE_DIR / "alert_state.json"     # dedup state (which alerts were already sent)
LOG_FILE: Path = BASE_DIR / "weather_bot.log"
LOG_MAX_BYTES: int = 5 * 1024 * 1024                 # 5 MB per log file
LOG_BACKUP_COUNT: int = 3

# ---------------------------------------------------------------------------
# SMTP settings (defaults tuned for Gmail)
# ---------------------------------------------------------------------------
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_SSL: bool = os.getenv("SMTP_USE_SSL", "false").lower() in ("1", "true", "yes")


def validate() -> list[str]:
    """Return a list of human-readable problems with the current config."""
    problems: list[str] = []
    if not API_KEY:
        problems.append("API_KEY is missing (set it in .env)")
    if SEND_ALERTS:
        if not SENDER_EMAIL or not SENDER_PASSWORD or not RECEIVER_EMAIL:
            problems.append(
                "Email settings incomplete: SENDER_EMAIL, SENDER_PASSWORD and RECEIVER_EMAIL are required"
            )
    return problems
