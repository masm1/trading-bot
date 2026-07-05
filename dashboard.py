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

from flask import Flask, jsonify, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ig_service import IGService
from demo_trader import place_top_signal_orders, print_open_positions, run_demo_trade_plan
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
    FINNHUB_API_KEY,
    LIVE_MARKET_SYMBOLS,
    MARKET_OPEN_AUTO_MODE,
    MARKET_OPEN_TIME,
    looks_like_placeholder,
)
from mapping import PRICE_SYMBOL_MAP

from logger import (
    CLOSED_POSITIONS_FILE,
    DEMO_ORDERS_FILE,
    OPEN_POSITIONS_FILE,
    PAPER_TRADES_FILE,
    POSITIONS_LOG_FILE,
    TRADES_LOG_FILE,
    create_log_files_if_missing,
    fetch_latest_rows,
    get_last_update,
    fetch_row_count,
    get_dashboard_status,
    log_event,
)

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

# Trading configuration
EPIC_MAP = {
    "AAPL": "UA.D.AAPL.CFD.IP",
    "AMZN": "UA.D.AMZN.CFD.IP",
    "TSLA": "UA.D.TSLA.CFD.IP",
    "MSFT": "UA.D.MSFT.CFD.IP",
    "GOOGL": "UA.D.GOOG.CFD.IP"
}

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

        if AUTO_SIGNAL_DEMO_TRADING:
            signal_candidates = run_dashboard_signal_cycle(price_tracker)
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
    if not AUTO_DEMO_TRADING and not AUTO_SIGNAL_DEMO_TRADING:
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


def read_recent_paper_trade_ideas(limit=15):
    rows = read_recent_db_rows("paper_trades", PAPER_TRADES_FILE, limit=max(limit * 5, 100))
    rows = [row for row in rows if (row.get("signal") or "").strip().upper() != "NO_SIGNAL"]
    return rows[:limit]


def paper_trade_watch_rows(watchlist_rows, limit=6):
    rows = []
    for item in watchlist_rows:
        stage = item.get("stage", "")
        if stage in ["EVENT_COMPLETE", "MARKET_OPEN_WINDOW_COMPLETE"]:
            continue

        rows.append(
            {
                "timestamp": item.get("watch_time", ""),
                "symbol": item.get("symbol", ""),
                "signal": "WATCHING",
                "paper_action": f"Waiting for {stage.replace('_', ' ').title()} before CALL/PUT idea",
                "change_percent": "",
                "notes": item.get("notes", ""),
            }
        )

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
                row["stage"] == "MARKET_OPEN_WINDOW_COMPLETE",
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

    age_seconds = max(int((datetime.utcnow() - ts).total_seconds()), 0)
    state = "fresh" if age_seconds <= 120 else "stale"
    return {
        "timestamp": timestamp,
        "message": heartbeat.get("notes", ""),
        "state": state,
        "age_seconds": age_seconds,
    }


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
            }
        )

    LIVE_MARKETS_CACHE["updated_at"] = now
    LIVE_MARKETS_CACHE["rows"] = rows
    return rows


def fetch_price_quote(symbol):
    if requests is None or looks_like_placeholder(FINNHUB_API_KEY):
        return latest_logged_price_quote(symbol)

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
            return latest_logged_price_quote(symbol)

        data = response.json()
        current = to_float(data.get("c"))
        previous = to_float(data.get("pc"))
        if current is None or previous in (None, 0):
            return latest_logged_price_quote(symbol)

        change = current - previous
        change_percent = (change / previous) * 100
        return {
            "price": round(current, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "direction": price_direction(change),
        }
    except Exception:
        return latest_logged_price_quote(symbol)


def latest_logged_price_quote(symbol):
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
        }

    return {
        "price": "",
        "change": "",
        "change_percent": "",
        "direction": "flat",
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
    paper_trades = read_recent_paper_trade_ideas(limit=15)
    demo_orders = read_latest_db_rows("demo_orders", DEMO_ORDERS_FILE, limit=15)
    trade_log = latest_trade_log_rows(limit=20)
    bot_heartbeat = latest_bot_heartbeat()
    watchlist_rows = dashboard_watchlist()
    paper_trade_rows = paper_trades or paper_trade_watch_rows(watchlist_rows)
    stage_summary = watchlist_stage_summary(watchlist_rows)
    price_ticker = dashboard_price_ticker(watchlist_rows)

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
        "paper_trade_count": len(paper_trades),
        "demo_order_count": live_log_count(DEMO_ORDERS_FILE),
        "watchlist_count": len(watchlist_rows),
        "watchlist_mode": "Market Open" if MARKET_OPEN_AUTO_MODE else "Earnings",
        "watchlist_time_label": "Market Open" if MARKET_OPEN_AUTO_MODE else "Earnings Time",
        "config_status": {
            "market_open_auto_mode": MARKET_OPEN_AUTO_MODE,
            "auto_signal_demo_trading": AUTO_SIGNAL_DEMO_TRADING,
            "auto_demo_trading": AUTO_DEMO_TRADING,
            "market_open_time": MARKET_OPEN_TIME,
        },
        "ig_status": get_dashboard_status("ig_status") or "",
        "bot_status": bot_status_details(bot_heartbeat),
        "watchlist_stage_summary": stage_summary,
        "price_ticker": price_ticker,
        "live_markets": dashboard_live_markets(),
        "watchlist": watchlist_rows,
        "paper_trades": paper_trade_rows,
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


if __name__ == "__main__":
    create_log_files_if_missing()
    start_trading_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
