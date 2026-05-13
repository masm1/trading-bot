import csv
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import (
    MARKET_OPEN_BASE_MINUTES,
    MARKET_OPEN_CHECK_END_MINUTES,
    MARKET_OPEN_CHECK_START_MINUTES,
    MARKET_OPEN_TIME,
    MARKET_OPEN_TIMEZONE,
    MARKET_OPEN_WATCHLIST_FILE,
)

PROJECT_DIR = Path(__file__).resolve().parent
WATCHLIST_FILE = PROJECT_DIR / MARKET_OPEN_WATCHLIST_FILE


@dataclass
class MarketOpenItem:
    symbol: str
    active: bool = True
    notes: str = ""


def load_market_open_watchlist():
    if not WATCHLIST_FILE.exists():
        print(f"{WATCHLIST_FILE.name} was not found.")
        return []

    items = []
    with WATCHLIST_FILE.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            raw_active = (row.get("active") or "yes").strip().lower()
            notes = (row.get("notes") or "").strip()

            if not symbol:
                continue

            active = raw_active in ["yes", "y", "true", "1", "active"]
            if not active:
                print(f"Skipping {symbol}: active is not yes.")
                continue

            items.append(MarketOpenItem(symbol=symbol, active=active, notes=notes))

    return items


def get_market_open_stage(now=None):
    market_now = _market_now(now)
    open_time = _parse_market_open_time()
    market_open = datetime.combine(market_now.date(), open_time, tzinfo=market_now.tzinfo)
    minutes_from_open = (market_now - market_open).total_seconds() / 60

    if minutes_from_open < 0:
        return "WAITING_FOR_MARKET_OPEN"
    if 0 <= minutes_from_open < MARKET_OPEN_BASE_MINUTES:
        return "SAVE_BASE_PRICE"
    if MARKET_OPEN_CHECK_START_MINUTES <= minutes_from_open < MARKET_OPEN_CHECK_END_MINUTES:
        return "CHECK_MARKET_OPEN_SIGNAL"
    if minutes_from_open < MARKET_OPEN_CHECK_START_MINUTES:
        return "WAITING_FOR_SIGNAL_WINDOW"

    return "MARKET_OPEN_WINDOW_COMPLETE"


def describe_market_open_clock(now=None):
    market_now = _market_now(now)
    return market_now.strftime("%Y-%m-%d %H:%M:%S %Z")


def _market_now(now=None):
    try:
        tz = ZoneInfo(MARKET_OPEN_TIMEZONE)
    except ZoneInfoNotFoundError:
        print(f"Unknown MARKET_OPEN_TIMEZONE={MARKET_OPEN_TIMEZONE}. Falling back to local time.")
        return now or datetime.now()

    if now is None:
        return datetime.now(tz)

    if now.tzinfo is None:
        return now.astimezone().astimezone(tz)

    return now.astimezone(tz)


def _parse_market_open_time():
    try:
        hour_text, minute_text = MARKET_OPEN_TIME.split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))
    except ValueError:
        print(f"Bad MARKET_OPEN_TIME={MARKET_OPEN_TIME}. Falling back to 09:30.")
        return time(hour=9, minute=30)
