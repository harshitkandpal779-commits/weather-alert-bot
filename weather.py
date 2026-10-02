"""
Weather data layer for the Advanced Weather Alert Bot.

Talks to WeatherAPI.com and returns rich, typed snapshots:
  * current conditions (temp, feels-like, wind, gusts, pressure, humidity,
    visibility, UV, cloud, precipitation, AQI with pollutant breakdown)
  * multi-day forecast (daily min/max, rain/snow chance & mm, hourly curves)
  * official weather alerts from the API

Includes retries with exponential backoff and polite rate-limit handling.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

import requests

import config

log = logging.getLogger("weather")

BASE_URL = "https://api.weatherapi.com/v1"
REQUEST_TIMEOUT = 20          # seconds
MAX_RETRIES = 3               # extra attempts after the first failure


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class AirQuality:
    aqi_us: int = 0
    pm2_5: float = 0.0
    pm10: float = 0.0
    o3: float = 0.0
    no2: float = 0.0
    so2: float = 0.0
    co: float = 0.0

    def category(self) -> str:
        """US EPA AQI category label."""
        a = self.aqi_us
        if a <= 50:
            return "Good"
        if a <= 100:
            return "Moderate"
        if a <= 150:
            return "Unhealthy for Sensitive Groups"
        if a <= 200:
            return "Unhealthy"
        if a <= 300:
            return "Very Unhealthy"
        return "Hazardous"


@dataclass
class CurrentWeather:
    location_name: str
    region: str
    country: str
    localtime: str
    tz_id: str
    temp_c: float
    temp_f: float
    feels_like_c: float
    condition: str
    is_day: bool
    humidity: int
    wind_kph: float
    wind_dir: str
    gust_kph: float
    pressure_mb: float
    precip_mm: float
    rain_mm: float
    snow_cm: float
    cloud_pct: int
    visibility_km: float
    uv: float
    dewpoint_c: float
    air_quality: AirQuality = field(default_factory=AirQuality)


@dataclass
class ForecastDay:
    date: str                    # YYYY-MM-DD
    max_temp_c: float
    min_temp_c: float
    avg_temp_c: float
    daily_condition: str
    will_it_rain: bool
    chance_of_rain: int
    rain_mm: float
    will_it_snow: bool
    chance_of_snow: int
    snow_cm: float
    max_wind_kph: float
    uv: float
    sunrise: str
    sunset: str
    hourly: list[dict] = field(default_factory=list)   # simplified hourly slices


@dataclass
class WeatherAlert:
    event: str
    severity: str
    headline: str
    effective: str
    expires: str
    description: str
    area: str


@dataclass
class LocationInfo:
    name: str
    display: str
    lat: float
    lon: float
    tz_id: str


# ---------------------------------------------------------------------------
# HTTP helper with retry / backoff
# ---------------------------------------------------------------------------
def _get(endpoint: str, params: dict) -> dict | None:
    url = f"{BASE_URL}/{endpoint}.json"
    params = {**params, "key": config.API_KEY}

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 401 or resp.status_code == 403:
                log.error("API key rejected (HTTP %s). Check API_KEY in .env.", resp.status_code)
                return None
            if resp.status_code == 429:
                wait = min(60, 5 * attempt) + random.uniform(0, 2)
                log.warning("Rate limited by WeatherAPI (429). Waiting %.0fs...", wait)
                time.sleep(wait)
                continue
            if 400 <= resp.status_code < 500:
                # Client error — retrying will not help
                try:
                    code = resp.json().get("error", {}).get("code")
                except ValueError:
                    code = "?"
                log.error("WeatherAPI client error HTTP %s (code %s) on /%s. Details: %s",
                          resp.status_code, code, endpoint,
                          resp.text[:200] if resp.ok is False else "")
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            wait = min(30, 2 ** attempt) + random.uniform(0, 1)
            log.warning("Request failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt, MAX_RETRIES + 1, exc, wait)
            if attempt <= MAX_RETRIES:
                time.sleep(wait)
    log.error("Giving up on %s after %d attempts.", endpoint, MAX_RETRIES + 1)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def search_locations(query: str, limit: int = 8) -> list[LocationInfo]:
    """Autocomplete/search for places (used by the CLI)."""
    data = _get("search", {"q": query})
    if not data:
        return []
    return [
        LocationInfo(
            name=item["name"],
            display=f'{item["name"]}, {item.get("region", "")}, {item.get("country", "")}'.replace(", ,", ",").strip(", "),
            lat=item["lat"],
            lon=item["lon"],
            tz_id=item.get("tz_id", ""),
        )
        for item in data
    ]


def _aqi_from_pm25(pm25: float) -> int:
    """US EPA AQI computed from a PM2.5 concentration (µg/m³, 24h breakpoints)."""
    if pm25 <= 0:
        return 0
    bp = [(0, 12.0, 0, 50), (12.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
          (55.5, 150.4, 151, 200), (150.5, 250.4, 201, 300),
          (250.5, 350.4, 301, 400), (350.5, 500.4, 401, 500)]
    for c_lo, c_hi, i_lo, i_hi in bp:
        if c_lo <= pm25 <= c_hi:
            return round((i_hi - i_lo) / (c_hi - c_lo) * (pm25 - c_lo) + i_lo)
    return 500


def _parse_air_quality(node: dict) -> AirQuality:
    """WeatherAPI reports pollutant concentrations (µg/m³ etc.) plus
    us-epa-index / gb-defra-index sub-objects that give the AQI *category*
    (1=Good … 6>Hazardous). We convert the PM2.5-based category back to an
    approximate US EPA AQI number using the standard breakpoints; when the
    plan doesn't expose the index at all we estimate it from raw PM2.5."""
    _AQI_RANGES = [(0, 50), (51, 100), (101, 150), (151, 200), (201, 300), (301, 400)]
    pm25 = float(node.get("pm2_5", 0) or 0)
    idx_node = node.get("us-epa-index")
    if isinstance(idx_node, dict):                    # forecast-style nesting
        idx = int(idx_node.get("pm2_5", 0) or 0)
    else:                                             # plain integer or missing
        idx = int(idx_node or 0)
    if 1 <= idx <= 6:
        lo, hi = _AQI_RANGES[idx - 1]
        aqi = (lo + hi) // 2          # representative value for the category
    elif pm25 > 0:
        aqi = _aqi_from_pm25(pm25)    # estimate from raw concentration
    else:
        aqi = 0
    return AirQuality(
        aqi_us=aqi,
        pm2_5=float(node.get("pm2_5", 0) or 0),
        pm10=float(node.get("pm10", 0) or 0),
        o3=float(node.get("o3", 0) or 0),
        no2=float(node.get("no2", 0) or 0),
        so2=float(node.get("so2", 0) or 0),
        co=float(node.get("co", 0) or 0),
    )


def get_current(city: str) -> CurrentWeather | None:
    """Fetch current conditions + live air quality for a city.

    Note: the WeatherAPI "explore" plan does not include the AQI field, so
    we estimate a US-EPA-style AQI from the raw PM2.5 reading when the API
    omits it (standard EPA breakpoint interpolation).
    """
    data = _get("current", {"q": city, "aqi": "yes"})
    if not data:
        return None
    loc = data.get("location", {})
    cur = data.get("current", {})
    cond = cur.get("condition", {})
    aqi_node = cur          # on plans that support AQI the fields are inline

    return CurrentWeather(
        location_name=loc.get("name", city),
        region=loc.get("region", ""),
        country=loc.get("country", ""),
        localtime=loc.get("localtime", ""),
        tz_id=loc.get("tz_id", ""),
        temp_c=float(cur.get("temp_c", 0)),
        temp_f=float(cur.get("temp_f", 0)),
        feels_like_c=float((cur.get("feelslike_c") or cur.get("temp_c", 0))),
        condition=cond.get("text", "Unknown"),
        is_day=bool(cur.get("is_day", 1)),
        humidity=int(cur.get("humidity", 0)),
        wind_kph=float(cur.get("wind_kph", 0)),
        wind_dir=cur.get("wind_dir", ""),
        gust_kph=float(cur.get("gust_kph", 0)),
        pressure_mb=float(cur.get("pressure_mb", 0)),
        precip_mm=float(cur.get("precip_mm", 0)),
        rain_mm=float(cur.get("rain_mm", 0)),
        snow_cm=float(cur.get("snow_cm", 0)),
        cloud_pct=int(cur.get("cloud", 0)),
        visibility_km=float(cur.get("vis_km", 10)),
        uv=float(cur.get("uv", 0)),
        dewpoint_c=float(cur.get("dewpoint_c", 0)),
        air_quality=_parse_air_quality(aqi_node),
    )


def get_forecast(city: str, days: int | None = None) -> tuple[list[ForecastDay], list[WeatherAlert]]:
    """Fetch a `days`-day forecast plus any official weather alerts."""
    days = max(1, min(days or config.FORECAST_DAYS, 10))
    data = _get("forecast", {"q": city, "dt": "today", "days": days,
                             "alerts": "yes", "aqi": "yes"})
    if not data:
        return [], []

    days_out: list[ForecastDay] = []
    for d in (data.get("forecast", {}) or {}).get("forecastday", []) or []:
        day = d.get("day", {})
        hourly = [
            {
                "time": h.get("time", "")[-5:],
                "temp_c": h.get("temp_c"),
                "chance_of_rain": h.get("chance_of_rain", 0),
                "chance_of_snow": h.get("chance_of_snow", 0),
                "condition": (h.get("condition") or {}).get("text", ""),
                "wind_kph": h.get("wind_kph", 0),
            }
            for h in d.get("hour", []) or []
        ]
        days_out.append(ForecastDay(
            date=d.get("date", ""),
            max_temp_c=float(day.get("maxtemp_c", 0)),
            min_temp_c=float(day.get("mintemp_c", 0)),
            avg_temp_c=float(day.get("avgtemp_c", 0)),
            daily_condition=(day.get("condition") or {}).get("text", "Unknown"),
            will_it_rain=bool(day.get("daily_will_it_rain", 0)),
            chance_of_rain=int(day.get("daily_chance_of_rain", 0) or 0),
            rain_mm=float(day.get("totalprecip_mm", 0) or 0),
            will_it_snow=bool(day.get("daily_will_it_snow", 0)),
            chance_of_snow=int(day.get("daily_chance_of_snow", 0) or 0),
            snow_cm=float(day.get("totalsnow_cm", 0) or 0),
            max_wind_kph=float(day.get("maxwind_kph", 0) or 0),
            uv=float(day.get("uv", 0) or 0),
            sunrise=d.get("astro", {}).get("sunrise", ""),
            sunset=d.get("astro", {}).get("sunset", ""),
            hourly=hourly,
        ))

    alerts_out: list[WeatherAlert] = []
    alerts_node = ((data.get("forecast") or {}).get("forecastday") or [{}])
    for d in alerts_node:
        for a in ((d.get("alert") or {}).get("event") or []):
            alerts_out.append(WeatherAlert(
                event=a.get("event", "Weather Alert"),
                severity=a.get("severity", "Unknown"),
                headline=a.get("headline", ""),
                effective=a.get("effective", ""),
                expires=a.get("expires", ""),
                description=a.get("desc", ""),
                area=a.get("area", ""),
            ))

    return days_out, alerts_out
