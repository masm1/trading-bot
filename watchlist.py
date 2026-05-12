import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
WATCHLIST_FILE = PROJECT_DIR / "earnings_watchlist.csv"
TIME_FORMAT = "%Y-%m-%d %H:%M"


@dataclass
class EarningsItem:
    symbol: str
    earnings_datetime: datetime
    active: bool = True
    notes: str = ""


def load_watchlist():
    if not WATCHLIST_FILE.exists():
        print("earnings_watchlist.csv was not found.")
        return []

    items = []
    with WATCHLIST_FILE.open("r", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            raw_time = (row.get("earnings_datetime") or "").strip()
            raw_active = (row.get("active") or "yes").strip().lower()
            notes = (row.get("notes") or "").strip()

            if not symbol or not raw_time:
                continue

            active = raw_active in ["yes", "y", "true", "1", "active"]
            if not active:
                print(f"Skipping {symbol}: active is not yes.")
                continue

            try:
                earnings_datetime = datetime.strptime(raw_time, TIME_FORMAT)
            except ValueError:
                print(f"Skipping {symbol}: bad time format '{raw_time}'")
                print("Use this format: YYYY-MM-DD HH:MM")
                continue

            items.append(
                EarningsItem(
                    symbol=symbol,
                    earnings_datetime=earnings_datetime,
                    active=active,
                    notes=notes,
                )
            )

    return items


def get_symbols(items):
    return [item.symbol for item in items]


def get_event_stage(item, now):
    minutes_from_earnings = (now - item.earnings_datetime).total_seconds() / 60

    if minutes_from_earnings < -15:
        return "WAITING_FOR_T_MINUS_15"
    if -15 <= minutes_from_earnings < 15:
        return "SAVE_BASE_PRICE"
    if 15 <= minutes_from_earnings < 30:
        return "CHECK_T_PLUS_15"
    if 30 <= minutes_from_earnings < 45:
        return "CHECK_T_PLUS_30"
    if 45 <= minutes_from_earnings < 90:
        return "CHECK_T_PLUS_45"

    return "EVENT_COMPLETE"
