# -*- coding: utf-8 -*-
import csv
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
import statistics
import os
import sys
import io
import time

try:
    import requests
except ImportError:
    requests = None

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ig_service import IGService
from demo_trader import (
    place_top_signal_orders,
    place_top_trend_buy_order,
    print_open_positions,
    run_demo_trade_plan,
    _calculate_demo_size,
)
from tracker import PriceTracker
from watchlist import get_event_stage, load_watchlist
from market_open import (
    get_market_open_stage,
    load_market_open_watchlist,
    minutes_from_market_open,
)
from config import (
    AUTO_DEMO_TRADING,
    AUTO_SIGNAL_DEMO_TRADING,
    AUTO_TREND_BUY_TRADING,
    CALL_SIGNAL_THRESHOLD_PERCENT,
    DEMO_TRADE_ONCE_PER_SYMBOL_PER_DAY,
    FINNHUB_API_KEY,
    MARKET_OPEN_BASE_MINUTES,
    MARKET_OPEN_CHECK_END_MINUTES,
    MARKET_OPEN_CHECK_START_MINUTES,
    LIVE_MARKET_SYMBOLS,
    MARKET_OPEN_AUTO_MODE,
    MARKET_OPEN_TIME,
    MIN_SIGNAL_QUALITY,
    SIGNAL_CANDIDATE_POOL_SIZE,
    SIGNAL_DEMO_NOTIONAL_USD,
    TREND_BUY_MAX_NOTIONAL_USD,
    TREND_BUY_MIN_CHANGE_PERCENT,
    looks_like_placeholder,
    PAPER_TRADING,
    ALLOW_MANUAL_BUY,
    MANUAL_BUY_ALLOWLIST,
    MANUAL_BUY_RATE_LIMIT_WINDOW_SECONDS,
    MANUAL_BUY_RATE_LIMIT_MAX,
)
from mapping import EPIC_MAP, PRICE_SYMBOL_MAP, IG_SEARCH_MAP
from strategy import demo_direction_for_signal, detect_signal

from logger import (
    CLOSED_POSITIONS_FILE,
    DEMO_ORDERS_FILE,
    OPEN_POSITIONS_FILE,
    POSITIONS_LOG_FILE,
    TRADES_LOG_FILE,
    create_log_files_if_missing,
    fetch_latest_rows,
    get_last_update,
    fetch_row_count,
    get_dashboard_status,
    log_demo_order,
    log_event,
)

# Simple in-memory rate limiter and allowlist helpers for manual buys
_manual_buy_requests = {}

def _client_ip_allowed(ip):
    allowlist = [s.strip() for s in (MANUAL_BUY_ALLOWLIST or "").split(',') if s.strip()]
    if not allowlist:
        # No allowlist configured -> block by default
        return False
    return ip in allowlist

def _rate_limit_ok(ip):
    now = int(time.time())
    window = MANUAL_BUY_RATE_LIMIT_WINDOW_SECONDS
    maxreq = MANUAL_BUY_RATE_LIMIT_MAX
    lst = _manual_buy_requests.setdefault(ip, [])
    # prune old
    while lst and lst[0] <= now - window:
        lst.pop(0)
    if len(lst) >= maxreq:
        return False
    lst.append(now)
    return True

app = Flask(__name__)
CORS(app)
PROJECT_DIR = Path(__file__).resolve().parent
OPEN_POSITION_MAX_AGE = timedelta(hours=12)
RECENT_ACTIVITY_MAX_AGE = timedelta(hours=48)
TRADE_LOG_MAX_AGE = timedelta(hours=24)
PRICE_TICKER_CACHE_SECONDS = 60
PRICE_TICKER_CACHE = {
    "updated_at": 0,
    "rows": [],
}
LIVE_MARKETS_CACHE_SECONDS = 60
LIVE_MARKETS_CACHE = {
    "updated_at": 0,
    "rows": [],
}
YAHOO_SYMBOL_MAP = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
}

# Trading configuration
# Use the shared IG epic mapping from mapping.py.

# Global IG service instance
ig_service = None
price_tracker = None
scheduler = BackgroundScheduler()


def run_trading_cycle():
    """Run one cycle of trading operations."""
    global ig_service, price_tracker

    try:
        if ig_service is None:
            ig_service = IGService()
            if not ig_service.login():
                print("❌ Trading cycle: Login failed")
                return

        print("🔄 Running trading cycle...")

        if price_tracker is None:
            price_tracker = PriceTracker(ig_service)

        if AUTO_DEMO_TRADING:
            run_demo_trade_plan(ig_service)

        if AUTO_SIGNAL_DEMO_TRADING or AUTO_TREND_BUY_TRADING:
            signal_candidates = run_dashboard_signal_cycle(price_tracker)
            if AUTO_TREND_BUY_TRADING:
                orders_sent = place_top_trend_buy_order(ig_service, signal_candidates)
            else:
                orders_sent = place_top_signal_orders(ig_service, signal_candidates)
            log_event(
                timestamp=datetime.now(),
                symbol="SYSTEM",
                event="BOT_CYCLE_COMPLETE",
                notes=(
                    f"Dashboard scheduler checked {len(signal_candidates)} "
                    f"signal candidate(s); sent {orders_sent} order(s)."
                ),
            )

        try:
            print_open_positions(ig_service)
        except Exception as exc:
            print(f"Position refresh skipped: {exc}")

        print("✅ Trading cycle completed")

    except Exception as e:
        print(f"❌ Trading cycle error: {e}")


def start_trading_scheduler():
    """Start the background trading scheduler."""
    if not AUTO_DEMO_TRADING and not AUTO_SIGNAL_DEMO_TRADING and not AUTO_TREND_BUY_TRADING:
        print("Auto trading is disabled")
        return

    print("🚀 Starting trading scheduler (runs every 5 minutes)...")
    scheduler.add_job(
        func=run_trading_cycle,
        trigger=IntervalTrigger(minutes=5),
        id='trading_cycle',
        name='Trading Cycle',
        next_run_time=datetime.now(),
        replace_existing=True
    )
    scheduler.start()


def run_dashboard_signal_cycle(tracker):
    now = datetime.now()

    if MARKET_OPEN_AUTO_MODE:
        stage = get_market_open_stage(now)
        print(f"Market-open signal cycle stage: {stage}")
        signal_candidates = []
        watch_items = load_market_open_watchlist()

        if stage in [
            "MARKET_CLOSED_WEEKEND",
            "WAITING_FOR_MARKET_OPEN",
            "WAITING_FOR_SIGNAL_WINDOW",
            "MARKET_OPEN_WINDOW_COMPLETE",
        ]:
            log_event(
                timestamp=datetime.now(),
                symbol="SYSTEM",
                event="MARKET_OPEN_STAGE",
                notes=f"Stage={stage}; watched {len(watch_items)} symbol(s).",
            )
            return signal_candidates

        for item in watch_items:
            symbol = item.symbol
            if stage == "SAVE_BASE_PRICE":
                tracker.save_base_price(symbol)
            elif stage == "CHECK_MARKET_OPEN_SIGNAL":
                signal_info = tracker.check_signal(symbol)
                if signal_info:
                    signal_candidates.append(signal_info)

        if stage != "CHECK_MARKET_OPEN_SIGNAL":
            log_event(
                timestamp=datetime.now(),
                symbol="SYSTEM",
                event="MARKET_OPEN_STAGE",
                notes=f"Stage={stage}; watched {len(watch_items)} symbol(s).",
            )

        return signal_candidates

    signal_candidates = []
    for item in load_watchlist():
        symbol = item.symbol
        stage = get_event_stage(item, now)

        if stage == "SAVE_BASE_PRICE":
            tracker.save_base_price(symbol)
        elif stage.startswith("CHECK"):
            signal_info = tracker.check_signal(symbol)
            if signal_info:
                signal_candidates.append(signal_info)

    return signal_candidates


def calculate_sharpe_ratio(pl_values):
    if len(pl_values) < 2:
        return 0.0
    mean_pl = statistics.mean(pl_values)
    std_pl = statistics.stdev(pl_values)
    return mean_pl / std_pl if std_pl > 0 else 0.0


def calculate_max_drawdown(cumulative_pl):
    if not cumulative_pl:
        return 0.0
    peak = cumulative_pl[0]
    max_dd = 0.0
    for val in cumulative_pl:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
    return max_dd


def parse_timestamp(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None

    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%H:%M:%S",
        "%H:%M:%S.%f",
        "%H:%M",
        "%H:%M.%f",
        "%M:%S",
        "%M:%S.%f",
    ):
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt in ("%M:%S", "%M:%S.%f"):
                parsed = parsed.replace(year=datetime.now().year, month=datetime.now().month, day=datetime.now().day)
            if fmt == "%H:%M" or fmt == "%H:%M.%f":
                parsed = parsed.replace(year=datetime.now().year, month=datetime.now().month, day=datetime.now().day)
            return parsed
        except ValueError:
            continue

    return None


def format_timestamp(value):
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return ""

    ts = parse_timestamp(value)
    if ts:
        if isinstance(value, str) and re.match(r"^\d{1,2}(?::\d{2}){1,2}(?:\.\d+)?$", value):
            return ts.strftime("%H:%M:%S")
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str) and value:
        return value
    return ""


def comparable_timestamp(value):
    if isinstance(value, str) and not re.search(r"\d{4}-\d{2}-\d{2}", value):
        return None

    ts = parse_timestamp(value)
    if not ts:
        return None
    if ts.tzinfo is not None:
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def row_is_recent(row, max_age):
    ts = comparable_timestamp(row.get("timestamp", ""))
    if not ts:
        return False
    return datetime.utcnow() - ts <= max_age


def sort_rows_newest_first(rows):
    indexed_rows = list(enumerate(rows))
    indexed_rows.sort(
        key=lambda item: (
            comparable_timestamp(item[1].get("timestamp", "")) or datetime.min,
            item[0],
        ),
        reverse=True,
    )
    return [row for _, row in indexed_rows]


def format_row_timestamps(rows):
    formatted_rows = []
    for row in rows:
        output = dict(row)
        timestamp = output.get("timestamp")
        if timestamp:
            formatted = format_timestamp(timestamp)
            if formatted:
                output["timestamp"] = formatted
        formatted_rows.append(output)
    return formatted_rows


def calculate_trade_frequency(closed_positions):
    if not closed_positions:
        return 0.0

    timestamps = []
    for pos in closed_positions:
        ts = parse_timestamp(pos.get("timestamp", ""))
        if ts:
            timestamps.append(ts)

    if len(timestamps) < 2:
        return 0.0

    start = min(timestamps)
    end = max(timestamps)
    days = max((end - start).days, 1)
    return len(timestamps) / days


def read_latest_rows(path, limit=25):
    if not path.exists():
        return []

    rows = []
    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if not any(value.strip() if isinstance(value, str) else value for value in row.values()):
                continue
            rows.append(row)

    rows = sort_rows_newest_first(format_row_timestamps(rows))
    return rows[:limit]


def read_latest_db_rows(table, fallback_path, limit=25):
    try:
        rows = fetch_latest_rows(table, limit=max(limit * 5, 100))
        if rows:
            rows = sort_rows_newest_first(format_row_timestamps(rows))
            return rows[:limit]
    except Exception:
        pass

    return read_latest_rows(fallback_path, limit=limit)


def read_recent_db_rows(table, fallback_path, limit=25, max_age=RECENT_ACTIVITY_MAX_AGE):
    rows = read_latest_db_rows(table, fallback_path, limit=max(limit * 5, 100))
    rows = [row for row in rows if row_is_recent(row, max_age)]
    return rows[:limit]


def is_bot_heartbeat(row):
    return (row.get("event") or "").strip().upper() == "BOT_CYCLE_COMPLETE"


def is_trade_log_noise(row):
    event = (row.get("event") or "").strip().upper()
    noise_events = {
        "WAITING_FOR_T_MINUS_15",
        "EVENT_COMPLETE",
        "BASE_PRICE_FAILED",
        "NO_PRICE",
    }
    return event in noise_events


def latest_bot_heartbeat():
    rows = read_latest_db_rows("trade_log", TRADES_LOG_FILE, limit=100)
    for row in rows:
        if is_bot_heartbeat(row):
            return row
    return {}


def latest_trade_log_rows(limit=20):
    rows = read_latest_db_rows("trade_log", TRADES_LOG_FILE, limit=max(limit * 5, 100))
    rows = [
        row
        for row in rows
        if row_is_recent(row, TRADE_LOG_MAX_AGE)
        and not is_bot_heartbeat(row)
        and not is_trade_log_noise(row)
    ]
    return rows[:limit]


def read_current_open_positions():
    csv_rows = read_latest_rows(OPEN_POSITIONS_FILE, limit=100)
    if OPEN_POSITIONS_FILE.exists():
        return [row for row in csv_rows if row_is_recent(row, OPEN_POSITION_MAX_AGE)]

    rows = read_latest_db_rows("open_positions", OPEN_POSITIONS_FILE, limit=100)
    return [row for row in rows if row_is_recent(row, OPEN_POSITION_MAX_AGE)]


def dashboard_watchlist(limit=50):
    now = datetime.now()
    rows = []

    if MARKET_OPEN_AUTO_MODE:
        stage = get_market_open_stage(now)
        minutes_from_open = minutes_from_market_open(now)
        for item in load_market_open_watchlist():
            rows.append(
                {
                    "symbol": item.symbol,
                    "watch_time": MARKET_OPEN_TIME,
                    "stage": stage,
                    "minutes_from_event": minutes_from_open,
                    "notes": item.notes,
                }
            )

        rows.sort(
            key=lambda row: (
                row["stage"] in ["MARKET_OPEN_WINDOW_COMPLETE", "MARKET_CLOSED_WEEKEND"],
                abs(row["minutes_from_event"]),
                row["symbol"],
            )
        )
        return rows[:limit]

    for item in load_watchlist():
        stage = get_event_stage(item, now)
        minutes_from_event = int((now - item.earnings_datetime).total_seconds() / 60)
        rows.append(
            {
                "symbol": item.symbol,
                "watch_time": item.earnings_datetime.strftime("%Y-%m-%d %H:%M"),
                "stage": stage,
                "minutes_from_event": minutes_from_event,
                "notes": item.notes,
            }
        )

    rows.sort(
        key=lambda row: (
            row["stage"] == "EVENT_COMPLETE",
            abs(row["minutes_from_event"]),
            row["symbol"],
        )
    )
    return rows[:limit]


def watchlist_stage_summary(rows):
    if MARKET_OPEN_AUTO_MODE:
        buckets = [
            ("Closed", "MARKET_CLOSED_WEEKEND"),
            ("Waiting", "WAITING_FOR_MARKET_OPEN"),
            ("Base Window", "SAVE_BASE_PRICE"),
            ("Signal Window", "CHECK_MARKET_OPEN_SIGNAL"),
            ("Complete", "MARKET_OPEN_WINDOW_COMPLETE"),
        ]
    else:
        buckets = [
            ("Waiting", "WAITING_FOR_T_MINUS_15"),
            ("Base Window", "SAVE_BASE_PRICE"),
            ("Check +15", "CHECK_T_PLUS_15"),
            ("Check +30", "CHECK_T_PLUS_30"),
            ("Check +45", "CHECK_T_PLUS_45"),
            ("Complete", "EVENT_COMPLETE"),
        ]
    return [
        {
            "label": label,
            "stage": stage,
            "count": sum(1 for row in rows if row.get("stage") == stage),
        }
        for label, stage in buckets
    ]


def bot_status_details(heartbeat):
    timestamp = heartbeat.get("timestamp", "")
    ts = comparable_timestamp(timestamp)
    if not ts:
        return {
            "timestamp": "",
            "message": "No bot heartbeat yet.",
            "state": "unknown",
            "age_seconds": None,
        }

    now = datetime.utcnow() if ts.tzinfo is not None else datetime.now()
    age_seconds = max(int((now - ts).total_seconds()), 0)
    state = "fresh" if age_seconds <= 120 else "stale"
    message = readable_bot_status_message(heartbeat.get("notes", ""))
    if state == "stale" and message:
        message = f"Stale heartbeat. Last status: {message}"

    return {
        "timestamp": timestamp,
        "message": message,
        "state": state,
        "age_seconds": age_seconds,
    }


def readable_bot_status_message(notes):
    if not notes:
        return ""

    stage_labels = {
        "MARKET_CLOSED_WEEKEND": "Market closed for the weekend.",
        "WAITING_FOR_MARKET_OPEN": "Waiting for market open.",
        "SAVE_BASE_PRICE": "Saving base prices.",
        "WAITING_FOR_SIGNAL_WINDOW": "Waiting for the signal window.",
        "CHECK_MARKET_OPEN_SIGNAL": "Checking market-open signals.",
        "MARKET_OPEN_WINDOW_COMPLETE": "Market-open signal window complete.",
    }

    for stage, label in stage_labels.items():
        if stage in notes:
            return label

    return notes


def dashboard_price_ticker(watchlist_rows):
    now = time.time()
    if now - PRICE_TICKER_CACHE["updated_at"] < PRICE_TICKER_CACHE_SECONDS:
        return PRICE_TICKER_CACHE["rows"]

    rows = []
    for item in watchlist_rows:
        symbol = item.get("symbol", "")
        quote = fetch_price_quote(symbol)
        rows.append(
            {
                "symbol": symbol,
                "price": quote.get("price", ""),
                "change": quote.get("change", ""),
                "change_percent": quote.get("change_percent", ""),
                "direction": quote.get("direction", "flat"),
                "quote_source": quote.get("source", ""),
                "quote_message": quote.get("message", ""),
                "status": item.get("stage", ""),
            }
        )

    PRICE_TICKER_CACHE["updated_at"] = now
    PRICE_TICKER_CACHE["rows"] = rows
    return rows


def configured_live_markets():
    rows = []
    for item in LIVE_MARKET_SYMBOLS.split(","):
        item = item.strip()
        if not item:
            continue

        symbol, _, label = item.partition(":")
        symbol = symbol.strip().upper()
        label = label.strip() or symbol
        if symbol:
            rows.append({"symbol": symbol, "label": label})

    return rows


def dashboard_live_markets():
    now = time.time()
    if now - LIVE_MARKETS_CACHE["updated_at"] < LIVE_MARKETS_CACHE_SECONDS:
        return LIVE_MARKETS_CACHE["rows"]

    rows = []
    for market in configured_live_markets():
        quote = fetch_price_quote(market["symbol"])
        rows.append(
            {
                "symbol": market["symbol"],
                "label": market["label"],
                "price": quote.get("price", ""),
                "change": quote.get("change", ""),
                "change_percent": quote.get("change_percent", ""),
                "direction": quote.get("direction", "flat"),
                "quote_source": quote.get("source", ""),
                "quote_message": quote.get("message", ""),
            }
        )

    LIVE_MARKETS_CACHE["updated_at"] = now
    LIVE_MARKETS_CACHE["rows"] = rows
    return rows


def latest_signal_checks(limit=500):
    rows = read_latest_db_rows("trade_log", TRADES_LOG_FILE, limit=limit)
    latest = {}
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        event = (row.get("event") or "").strip().upper()
        if not symbol or symbol == "SYSTEM" or event != "SIGNAL_CHECK":
            continue
        if symbol not in latest:
            latest[symbol] = row
    return latest


def traded_today_symbols():
    if not DEMO_TRADE_ONCE_PER_SYMBOL_PER_DAY:
        return set()

    today = datetime.now().date().isoformat()
    traded = set()
    rows = read_latest_db_rows("demo_orders", DEMO_ORDERS_FILE, limit=500)
    valid_statuses = {
        "SENT",
        "SIGNAL_SENT",
        "TREND_BUY_SENT",
        "MANUAL_BUY_SENT",
    }
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        status = (row.get("status") or "").strip().upper()
        timestamp = row.get("timestamp") or ""
        if symbol and status in valid_statuses and timestamp.startswith(today):
            traded.add(symbol)
    return traded


def auto_buy_status(bot_status, watchlist_rows):
    armed = bool(AUTO_SIGNAL_DEMO_TRADING or AUTO_TREND_BUY_TRADING)
    stage = watchlist_rows[0].get("stage", "") if watchlist_rows else ""
    if not armed:
        readiness = "Disabled"
        tone = "danger"
    elif stage in ["CHECK_MARKET_OPEN_SIGNAL", "CHECK_T_PLUS_15", "CHECK_T_PLUS_30", "CHECK_T_PLUS_45"]:
        readiness = "Signal Window"
        tone = "good"
    elif stage in ["SAVE_BASE_PRICE"]:
        readiness = "Base Window"
        tone = "warn"
    else:
        readiness = "Armed"
        tone = "info"

    return {
        "armed": armed,
        "readiness": readiness,
        "tone": tone,
        "mode": "Trend Buy" if AUTO_TREND_BUY_TRADING else ("Signal Orders" if AUTO_SIGNAL_DEMO_TRADING else "Off"),
        "market_mode": "Market Open" if MARKET_OPEN_AUTO_MODE else "Earnings",
        "stage": stage or "Unknown",
        "bot_state": bot_status.get("state", "unknown"),
        "bot_message": bot_status.get("message", ""),
        "watchlist_symbols": [row.get("symbol", "") for row in watchlist_rows],
        "auto_demo_trading": AUTO_DEMO_TRADING,
        "auto_signal_demo_trading": AUTO_SIGNAL_DEMO_TRADING,
        "auto_trend_buy_trading": AUTO_TREND_BUY_TRADING,
        "paper_trading": PAPER_TRADING,
        "manual_buy_enabled": bool(PAPER_TRADING and ALLOW_MANUAL_BUY),
        "market_open_time": MARKET_OPEN_TIME,
        "base_window_minutes": MARKET_OPEN_BASE_MINUTES,
        "signal_window": f"{MARKET_OPEN_CHECK_START_MINUTES}-{MARKET_OPEN_CHECK_END_MINUTES}m",
        "min_quality": MIN_SIGNAL_QUALITY,
        "trend_buy_min_change_percent": TREND_BUY_MIN_CHANGE_PERCENT,
        "call_threshold_percent": CALL_SIGNAL_THRESHOLD_PERCENT,
        "max_notional_usd": TREND_BUY_MAX_NOTIONAL_USD if AUTO_TREND_BUY_TRADING else SIGNAL_DEMO_NOTIONAL_USD,
        "candidate_pool_size": SIGNAL_CANDIDATE_POOL_SIZE,
        "once_per_symbol_per_day": DEMO_TRADE_ONCE_PER_SYMBOL_PER_DAY,
    }


def auto_buy_candidates(watchlist_rows, price_ticker):
    signal_checks = latest_signal_checks()
    traded_symbols = traded_today_symbols()
    ticker_by_symbol = {
        (row.get("symbol") or "").upper(): row
        for row in price_ticker
    }
    rows = []

    for item in watchlist_rows:
        symbol = (item.get("symbol") or "").strip().upper()
        stage = item.get("stage", "")
        latest_check = signal_checks.get(symbol, {})
        ticker = ticker_by_symbol.get(symbol, {})
        base_price = to_float(latest_check.get("base_price"))
        current_price = to_float(latest_check.get("current_price"))
        result = None

        if base_price is not None and current_price is not None:
            result = detect_signal(base_price, current_price)

        signal = result.get("signal") if result else (latest_check.get("signal") or "WAITING")
        change_percent = result.get("change_percent") if result else latest_check.get("change_percent", "")
        quality = result.get("quality") if result else ""
        direction = demo_direction_for_signal(signal)
        tradable_hint = "mapped" if symbol in EPIC_MAP else ("search" if symbol in IG_SEARCH_MAP else "unknown")
        reason = ""
        eligible = False

        if not (AUTO_SIGNAL_DEMO_TRADING or AUTO_TREND_BUY_TRADING):
            reason = "Auto trading is disabled."
        elif symbol in traded_symbols:
            reason = "Already traded today."
        elif stage not in ["CHECK_MARKET_OPEN_SIGNAL", "CHECK_T_PLUS_15", "CHECK_T_PLUS_30", "CHECK_T_PLUS_45"]:
            reason = f"Waiting for {stage.replace('_', ' ').title()}."
        elif not result:
            reason = "No signal check with base/current price yet."
        elif AUTO_TREND_BUY_TRADING and signal != "STRONG_RALLY":
            reason = "Trend buy only accepts strong rallies."
        elif AUTO_TREND_BUY_TRADING and to_float(change_percent) < TREND_BUY_MIN_CHANGE_PERCENT:
            reason = "Move is below trend buy threshold."
        elif to_float(quality) is not None and to_float(quality) < MIN_SIGNAL_QUALITY:
            reason = "Signal quality is below minimum."
        elif AUTO_SIGNAL_DEMO_TRADING and direction != "BUY" and not AUTO_TREND_BUY_TRADING:
            reason = "Signal would not create a buy order."
        elif tradable_hint == "unknown":
            reason = "No IG search mapping configured."
        else:
            eligible = True
            reason = "Eligible for auto buy."

        score_quality = to_float(quality) or 0
        score_change = to_float(change_percent) or 0
        rows.append(
            {
                "symbol": symbol,
                "stage": stage,
                "signal": signal,
                "quality": quality,
                "change_percent": change_percent,
                "price": ticker.get("price", current_price if current_price is not None else ""),
                "direction": "BUY" if eligible else (direction or ""),
                "eligible": eligible,
                "reason": reason,
                "tradable_hint": tradable_hint,
                "score": round(score_quality * 100 + max(score_change, 0), 2),
                "last_signal_time": latest_check.get("timestamp", ""),
            }
        )

    rows.sort(key=lambda row: (row["eligible"], row["score"], to_float(row["change_percent"]) or 0), reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def fetch_price_quote(symbol):
    if requests is None:
        return latest_logged_price_quote(symbol, "requests is not installed.")

    symbol = (symbol or "").strip().upper()
    if not symbol:
        return no_quote("Missing symbol.")

    if not looks_like_placeholder(FINNHUB_API_KEY):
        quote = fetch_finnhub_quote(symbol)
        if quote.get("price") != "":
            return quote

    quote = fetch_yahoo_quote(symbol)
    if quote.get("price") != "":
        return quote

    return latest_logged_price_quote(symbol, quote.get("message", "No live quote available."))


def fetch_finnhub_quote(symbol):
    try:
        response = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={
                "symbol": PRICE_SYMBOL_MAP.get(symbol.upper(), symbol.upper()),
                "token": FINNHUB_API_KEY,
            },
            timeout=8,
        )
        if response.status_code != 200:
            return no_quote(f"Finnhub returned HTTP {response.status_code}.")

        data = response.json()
        current = to_float(data.get("c"))
        previous = to_float(data.get("pc"))
        if current is None or previous in (None, 0):
            return no_quote("Finnhub returned an empty quote.")

        return build_quote(current, previous, "Finnhub")
    except Exception as exc:
        return no_quote(f"Finnhub unavailable: {exc}")


def fetch_yahoo_quote(symbol):
    yahoo_symbol = YAHOO_SYMBOL_MAP.get(symbol.upper(), symbol.upper())
    try:
        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}",
            params={"range": "2d", "interval": "1d"},
            timeout=8,
            headers={"User-Agent": "TradingBotDashboard/1.0"},
        )
        if response.status_code != 200:
            return no_quote(f"Yahoo returned HTTP {response.status_code}.")

        data = response.json()
        result = (data.get("chart", {}).get("result") or [None])[0]
        if not result:
            return no_quote("Yahoo returned an empty quote.")

        meta = result.get("meta", {})
        current = to_float(meta.get("regularMarketPrice"))
        previous = to_float(meta.get("chartPreviousClose") or meta.get("previousClose"))
        if current is None:
            closes = [
                to_float(value)
                for value in (
                    (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
                )
            ]
            closes = [value for value in closes if value is not None]
            if closes:
                current = closes[-1]
                if previous is None and len(closes) > 1:
                    previous = closes[-2]

        if current is None:
            return no_quote("Yahoo returned no current price.")
        if previous in (None, 0):
            previous = current

        return build_quote(current, previous, "Yahoo")
    except Exception as exc:
        return no_quote(f"Yahoo unavailable: {exc}")


def build_quote(current, previous, source):
    change = current - previous
    change_percent = (change / previous) * 100 if previous else 0
    return {
        "price": round(current, 2),
        "change": round(change, 2),
        "change_percent": round(change_percent, 2),
        "direction": price_direction(change),
        "source": source,
        "message": "",
    }


def latest_logged_price_quote(symbol, message=""):
    rows = read_latest_db_rows("trade_log", TRADES_LOG_FILE, limit=200)
    for row in rows:
        if (row.get("symbol") or "").upper() != symbol.upper():
            continue

        current = to_float(row.get("current_price"))
        change_percent = to_float(row.get("change_percent"))
        if current is None:
            continue

        return {
            "price": round(current, 2),
            "change": "",
            "change_percent": round(change_percent, 2) if change_percent is not None else "",
            "direction": price_direction(change_percent),
            "source": "Log",
            "message": message or "Using latest logged price.",
        }

    return no_quote(message or "No quote has been logged yet.")


def no_quote(message):
    return {
        "price": "",
        "change": "",
        "change_percent": "",
        "direction": "flat",
        "source": "",
        "message": message,
    }


def to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def price_direction(value):
    number = to_float(value)
    if number is None:
        return "flat"
    if number > 0:
        return "up"
    if number < 0:
        return "down"
    return "flat"


def count_csv_rows(path):
    if not path.exists():
        return 0

    count = 0
    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if any(value.strip() if isinstance(value, str) else value for value in row.values()):
                count += 1
    return count


def count_rows(table, fallback_path):
    try:
        count = fetch_row_count(table)
        if count > 0:
            return count
    except Exception:
        pass
    return count_csv_rows(fallback_path)


def live_log_count(path):
    return count_csv_rows(path)


def last_update_value():
    latest = read_latest_db_rows("trade_log", TRADES_LOG_FILE, limit=1)
    if latest:
        return latest[0].get("timestamp", "")

    last_update = get_last_update()
    if last_update:
        return last_update

    return ""


def dashboard_data():
    create_log_files_if_missing()
    open_positions = read_current_open_positions()
    closed_positions = read_latest_db_rows("closed_positions", CLOSED_POSITIONS_FILE, limit=15)
    if not closed_positions:
        closed_positions = closed_position_snapshots_from_orders()
    demo_orders = read_latest_db_rows("demo_orders", DEMO_ORDERS_FILE, limit=15)
    trade_log = latest_trade_log_rows(limit=20)
    bot_heartbeat = latest_bot_heartbeat()
    watchlist_rows = dashboard_watchlist()
    stage_summary = watchlist_stage_summary(watchlist_rows)
    price_ticker = dashboard_price_ticker(watchlist_rows)
    bot_status = bot_status_details(bot_heartbeat)
    auto_status = auto_buy_status(bot_status, watchlist_rows)
    auto_candidates = auto_buy_candidates(watchlist_rows, price_ticker)

    # Calculate profit/loss summary
    total_profit = 0.0
    total_loss = 0.0
    winning_trades = 0
    losing_trades = 0
    for pos in closed_positions:
        pl = float(pos.get('profit_loss', 0))
        if pl > 0:
            total_profit += pl
            winning_trades += 1
        elif pl < 0:
            total_loss += abs(pl)
            losing_trades += 1
    net_pl = total_profit - total_loss
    total_trades = winning_trades + losing_trades
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    avg_profit = total_profit / winning_trades if winning_trades > 0 else 0
    avg_loss = total_loss / losing_trades if losing_trades > 0 else 0

    # Prepare chart data: cumulative P/L over time
    chart_labels = []
    chart_data = []
    cumulative_pl = 0.0
    pl_values = []
    sorted_positions = sorted(
        closed_positions,
        key=lambda x: parse_timestamp(x.get('timestamp', '')) or datetime.min,
    )
    for pos in sorted_positions:
        pl = float(pos.get('profit_loss', 0))
        pl_values.append(pl)
        cumulative_pl += pl
        chart_labels.append(format_timestamp(pos.get('timestamp', '')))
        chart_data.append(cumulative_pl)

    # Calculate advanced analytics
    sharpe_ratio = calculate_sharpe_ratio(pl_values)
    max_drawdown = calculate_max_drawdown(chart_data)
    trade_frequency = calculate_trade_frequency(closed_positions)

    return {
        "positions": open_positions,
        "closed_positions": closed_positions,
        "total_profit": total_profit,
        "total_loss": total_loss,
        "net_pl": net_pl,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "avg_profit": avg_profit,
        "avg_loss": avg_loss,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "trade_frequency": trade_frequency,
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "last_update": last_update_value(),
        "trade_log_count": live_log_count(TRADES_LOG_FILE),
        "demo_order_count": live_log_count(DEMO_ORDERS_FILE),
        "watchlist_count": len(watchlist_rows),
        "watchlist_mode": "Market Open" if MARKET_OPEN_AUTO_MODE else "Earnings",
        "watchlist_time_label": "Market Open" if MARKET_OPEN_AUTO_MODE else "Earnings Time",
        "config_status": {
            "market_open_auto_mode": MARKET_OPEN_AUTO_MODE,
            "auto_signal_demo_trading": AUTO_SIGNAL_DEMO_TRADING,
            "auto_trend_buy_trading": AUTO_TREND_BUY_TRADING,
            "auto_demo_trading": AUTO_DEMO_TRADING,
            "market_open_time": MARKET_OPEN_TIME,
        },
        "ig_status": get_dashboard_status("ig_status") or "",
        "bot_status": bot_status,
        "auto_buy_status": auto_status,
        "auto_buy_candidates": auto_candidates,
        "watchlist_stage_summary": stage_summary,
        "price_ticker": price_ticker,
        "live_markets": dashboard_live_markets(),
        "watchlist": watchlist_rows,
        "demo_orders": demo_orders,
        "trade_log": trade_log,
    }


def latest_position_snapshots_from_log():
    rows = read_latest_rows(POSITIONS_LOG_FILE, limit=500)
    closed_deal_ids = {
        row.get("deal_id")
        for row in read_latest_rows(CLOSED_POSITIONS_FILE, limit=500)
        if row.get("deal_id")
    }

    closed_deal_ids_from_orders = {
        row.get("deal_id")
        for row in read_latest_rows(DEMO_ORDERS_FILE, limit=500)
        if row.get("deal_id") and (
            "STOP_LOSS" in (row.get("status") or "")
            or "TAKE_PROFIT" in (row.get("status") or "")
            or "CLOSE" in (row.get("status") or "")
        )
    }

    closed_deal_ids.update(closed_deal_ids_from_orders)

    latest = {}
    for row in rows:
        deal_id = row.get("deal_id") or row.get("instrument") or "unknown"
        if deal_id in closed_deal_ids:
            continue
        if deal_id not in latest:
            latest[deal_id] = row

    return list(latest.values())


def closed_position_snapshots_from_orders():
    closed_ids = {
        row.get("deal_id")
        for row in read_latest_rows(DEMO_ORDERS_FILE, limit=500)
        if row.get("deal_id")
        and (
            "STOP_LOSS" in (row.get("status") or "")
            or "TAKE_PROFIT" in (row.get("status") or "")
            or "CLOSE" in (row.get("status") or "")
        )
    }
    closed_ids = {deal_id for deal_id in closed_ids if deal_id}

    if not closed_ids:
        return []

    snapshots = []
    seen = set()
    for row in read_latest_rows(POSITIONS_LOG_FILE, limit=1000):
        deal_id = row.get("deal_id")
        if deal_id in closed_ids and deal_id not in seen:
            snapshots.append(row)
            seen.add(deal_id)

    return snapshots[:15]


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return render_template("dashboard.html", data=dashboard_data())


@app.route("/api/dashboard")
def api_dashboard():
    return jsonify(dashboard_data())


@app.route("/api/manual-buy", methods=["POST"])
def api_manual_buy():
    payload = request.get_json(silent=True) or {}
    symbol = (payload.get("symbol") or "").strip().upper()
    notional_usd = payload.get("notional_usd", SIGNAL_DEMO_NOTIONAL_USD)

    if not symbol:
        return jsonify({"success": False, "message": "Missing symbol."}), 400

    # Protect against accidental live buys: require PAPER_TRADING enabled and ALLOW_MANUAL_BUY set in .env
    if not PAPER_TRADING or not ALLOW_MANUAL_BUY:
        return jsonify({"success": False, "message": "Manual buys disabled on server. Set PAPER_TRADING=true and ALLOW_MANUAL_BUY=true in .env to enable."}), 403

    # Allowlist check: only configured IPs can perform manual buys
    client_ip = request.remote_addr or "unknown"
    if not _client_ip_allowed(client_ip):
        # Log blocked attempt for auditing
        log_event(
            timestamp=datetime.now(),
            symbol=symbol or "MANUAL_BUY",
            event="MANUAL_BUY_BLOCKED_IP",
            paper_action="Manual buy blocked - IP not allowed",
            notes=f"IP:{client_ip}",
        )
        return jsonify({"success": False, "message": f"IP {client_ip} not allowed to perform manual buys."}), 403

    # Rate limit per IP
    if not _rate_limit_ok(client_ip):
        # Log rate-limited attempt for auditing
        log_event(
            timestamp=datetime.now(),
            symbol=symbol or "MANUAL_BUY",
            event="MANUAL_BUY_RATE_LIMIT",
            paper_action="Manual buy blocked - rate limit",
            notes=f"IP:{client_ip}",
        )
        return jsonify({"success": False, "message": "Rate limit exceeded for manual buys. Try again later."}), 429

    result = manual_buy_order(symbol, notional_usd)
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


def manual_buy_order(symbol, notional_usd=SIGNAL_DEMO_NOTIONAL_USD):
    ig = IGService()
    if not ig.login():
        return {"success": False, "message": "IG login failed."}

    symbol_key = symbol.upper()
    epic = EPIC_MAP.get(symbol_key)
    if not epic:
        search_term = IG_SEARCH_MAP.get(symbol_key, symbol)
        epic = ig.search_market(search_term)

    current_price = ig.get_price_for_symbol(symbol_key, epic)
    if current_price is None and epic is None:
        return {"success": False, "message": f"Could not find IG market for {symbol}."}
    size = _calculate_demo_size(current_price, notional_usd)
    if size is None:
        return {"success": False, "message": "Could not calculate buy size from current price."}

    result = ig.place_demo_market_order(epic=epic, direction="BUY", size=size)
    status = "MANUAL_BUY_SENT" if result.get("success") else "MANUAL_BUY_FAILED"
    message = result.get("message", "")
    deal_reference = result.get("deal_reference", "")
    deal_id = result.get("deal_id", "")

    log_demo_order(
        timestamp=datetime.now(),
        symbol=symbol,
        epic=epic,
        direction="BUY",
        size=size,
        status=status,
        deal_reference=deal_reference,
        deal_id=deal_id,
        message=message,
    )
    log_event(
        timestamp=datetime.now(),
        symbol=symbol,
        event=f"MANUAL_BUY_{status}",
        paper_action="Manual BUY from dashboard",
        notes=message,
    )

    return {"success": result.get("success", False), "message": message, "status": status}


if __name__ == "__main__":
    create_log_files_if_missing()
    start_trading_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
