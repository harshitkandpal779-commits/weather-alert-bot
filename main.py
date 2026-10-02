"""
Advanced Weather Alert Bot — main entry point.

Modes
-----
  python main.py run            Continuous monitor (default): checks every
                                CHECK_INTERVAL_MINUTES, emails alerts and a
                                daily morning briefing for every city in CITY.
  python main.py check          One-shot alert check (all cities).
  python main.py status         Console weather report (no email).
  python main.py briefing       Send today's full HTML briefing by email.
  python main.py test-email     Send a test email to verify SMTP settings.
  python main.py search <name>  Look up valid location names for .env.

Features: multi-city monitoring, heat/cold/rain/snow/wind/gust/UV/visibility/
pressure/AQI rules, official government alerts, severity levels, per-alert
email cooldown (no spam), daily briefing, rotating file logs, graceful exit.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import signal
import sys
import time
from datetime import datetime

import config
import notifier
from alerts import collect_alerts, evaluate_current, evaluate_forecast, evaluate_official
from weather import get_current, get_forecast, search_locations

log = logging.getLogger("bot")
_RUNNING = True


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------
def setup_logging(verbose: bool = False) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        fileh = logging.handlers.RotatingFileHandler(
            config.LOG_FILE, maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT, encoding="utf-8")
        fileh.setFormatter(fmt)
        root.addHandler(fileh)
    except OSError as exc:
        log.warning("File logging disabled: %s", exc)


def _stop(signum, frame) -> None:  # noqa: ANN001
    global _RUNNING
    log.info("Received signal %s — shutting down gracefully...", signum)
    _RUNNING = False


# ---------------------------------------------------------------------------
# Core cycle
# ---------------------------------------------------------------------------
def check_city(city: str, *, send_email: bool = True) -> int:
    """Fetch data, evaluate rules, notify. Returns number of new alerts."""
    cur = get_current(city)
    days, official = get_forecast(city)
    if cur is None and not days:
        log.error("No weather data available for %s — skipping this cycle.", city)
        return 0

    fresh = collect_alerts(city, cur, days, official)
    notifier.print_console_alerts(fresh)

    if fresh and send_email and config.SEND_ALERTS:
        if notifier.notify_alerts(fresh):
            log.info("Emailed %d alert(s) for %s.", len(fresh), city)
    return len(fresh)


def send_briefing(city: str) -> bool:
    cur = get_current(city)
    days, official = get_forecast(city)
    active: list = []
    if cur or days or official:
        # Show currently-relevant alerts WITHOUT consuming their cooldown
        active = (evaluate_current(city, cur) if cur else []) \
            + evaluate_forecast(city, days) + evaluate_official(city, official)
    notifier.print_console_briefing(city, cur, days, official)
    if config.SEND_ALERTS:
        return notifier.notify_briefing(city, cur, days, active)
    return True


def run_cycle(cities: list[str]) -> None:
    for city in cities:
        try:
            check_city(city)
        except Exception:                       # noqa: BLE001 — keep the loop alive
            log.exception("Unexpected error while checking %s", city)
        time.sleep(2)                           # be polite to the API between cities


def monitor(cities: list[str]) -> None:
    interval = max(5, config.CHECK_INTERVAL_MINUTES) * 60
    last_briefing_date: str | None = None
    log.info("Monitor started: cities=%s, interval=%d min, hot≥%g°C, cold≤%g°C, AQI≥%d",
             cities, config.CHECK_INTERVAL_MINUTES, config.HOT_THRESHOLD,
             config.COLD_THRESHOLD, config.AQI_THRESHOLD)

    while _RUNNING:
        now = datetime.now()
        # Daily briefing at DAILY_BRIEFING_HOUR, once per day
        if now.hour == config.DAILY_BRIEFING_HOUR and last_briefing_date != now.date().isoformat():
            for city in cities:
                try:
                    log.info("Sending daily briefing for %s…", city)
                    send_briefing(city)
                except Exception:               # noqa: BLE001
                    log.exception("Briefing failed for %s", city)
            last_briefing_date = now.date().isoformat()

        run_cycle(cities)
        # Sleep in small slices so Ctrl+C exits promptly
        deadline = time.time() + interval
        while _RUNNING and time.time() < deadline:
            time.sleep(min(5, max(0.5, deadline - time.time())))
    log.info("Stopped.")


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------
def cmd_search(query: str) -> int:
    results = search_locations(query)
    if not results:
        print(f"No matches for {query!r}.")
        return 1
    print(f"Matches for {query!r}:")
    for r in results:
        print(f"  📍 {r.display}  (lat {r.lat}, lon {r.lon}, tz {r.tz_id})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="weather-bot",
                                description="Advanced Weather Alert Bot 🤖")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="continuous monitoring (default)")
    sub.add_parser("check", help="one-shot alert check")
    sub.add_parser("status", help="console weather report (no email)")
    sub.add_parser("briefing", help="send daily briefing email now")
    sub.add_parser("test-email", help="send a test email")
    sp = sub.add_parser("search", help="look up location names")
    sp.add_argument("query", nargs="+", help="place name to search")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    problems = config.validate()
    if problems:
        for msg in problems:
            log.error("Config problem: %s", msg)
        log.error("Fix your .env file and try again.")
        return 2

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    cities = config.CITIES

    cmd = args.cmd or "run"
    if cmd == "search":
        return cmd_search(" ".join(args.query))

    if cmd == "test-email":
        ok = notifier.send_email(
            "✅ Weather Bot test email",
            notifier._page("Test Successful", "SMTP configuration verified",
                           "<p>Your Advanced Weather Alert Bot can send email. "
                           f"Monitoring: <b>{', '.join(cities)}</b></p>"))
        print("Test email sent ✔" if ok else "Test email FAILED — see log above ✘")
        return 0 if ok else 1

    if cmd == "status":
        for city in cities:
            cur = get_current(city)
            days, official = get_forecast(city)
            notifier.print_console_briefing(city, cur, days, official)
        return 0

    if cmd == "check":
        total = sum(check_city(c) for c in cities)
        print(f"Done — {total} new alert(s) triggered across {len(cities)} city(ies).")
        return 0

    if cmd == "briefing":
        for city in cities:
            send_briefing(city)
        return 0

    # default: continuous monitor
    monitor(cities)
    return 0


if __name__ == "__main__":
    sys.exit(main())
