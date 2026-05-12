import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import (
    AUTO_CLOSE_DEMO_POSITIONS,
    AUTO_DEMO_TRADING,
    AUTO_SIGNAL_DEMO_TRADING,
    DEMO_STOP_LOSS_AMOUNT,
    DEMO_TAKE_PROFIT_AMOUNT,
    DEMO_TRADE_ONCE_PER_SYMBOL_PER_DAY,
    MAX_DRAWDOWN,
    MAX_DEMO_TRADES_PER_RUN,
    MAX_SIGNAL_DEMO_TRADES_PER_ROUND,
    MIN_SIGNAL_QUALITY,
    SIGNAL_CANDIDATE_POOL_SIZE,
    SIGNAL_DEMO_NOTIONAL_USD,
)
from logger import (
    CLOSED_POSITIONS_FILE,
    DEMO_ORDERS_FILE,
    log_closed_position,
    log_demo_order,
    log_event,
    log_position_snapshot,
    set_dashboard_status,
    write_open_positions,
)
from mapping import IG_SEARCH_MAP
from strategy import demo_direction_for_signal, signal_score

PROJECT_DIR = Path(__file__).resolve().parent
DEMO_TRADE_PLAN_FILE = PROJECT_DIR / "demo_trade_plan.csv"
CLOSE_ORDERS_SENT = set()


@dataclass
class DemoTradePlan:
    symbol: str
    search_term: str
    direction: str
    size: float
    active: bool
    notes: str = ""


def load_demo_trade_plan():
    if not DEMO_TRADE_PLAN_FILE.exists():
        print("demo_trade_plan.csv was not found.")
        return []

    plans = []
    with DEMO_TRADE_PLAN_FILE.open("r", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            raw_search_term = (row.get("search_term") or "").strip()
            search_term = raw_search_term or IG_SEARCH_MAP.get(symbol, symbol)
            direction = (row.get("direction") or "").strip().upper()
            raw_size = (row.get("size") or "").strip()
            raw_active = (row.get("active") or "no").strip().lower()
            notes = (row.get("notes") or "").strip()

            if not symbol or direction not in ["BUY", "SELL"]:
                continue

            try:
                size = float(raw_size)
            except ValueError:
                print(f"Skipping {symbol}: size must be a number.")
                continue

            active = raw_active in ["yes", "y", "true", "1", "active"]
            plans.append(
                DemoTradePlan(
                    symbol=symbol,
                    search_term=search_term,
                    direction=direction,
                    size=size,
                    active=active,
                    notes=notes,
                )
            )

    return plans


def run_demo_trade_plan(ig_service):
    if not AUTO_DEMO_TRADING:
        print("Auto demo trading is OFF. Set AUTO_DEMO_TRADING=true in .env to enable.")
        return

    plans = [plan for plan in load_demo_trade_plan() if plan.active]
    if not plans:
        print("No active demo trades found in demo_trade_plan.csv")
        return

    trades_sent = 0
    for plan in plans:
        if trades_sent >= MAX_DEMO_TRADES_PER_RUN:
            print(f"Max demo trades per run reached: {MAX_DEMO_TRADES_PER_RUN}")
            return

        if _already_traded_today(plan.symbol):
            print(f"{plan.symbol}: demo trade already sent today. Skipping.")
            continue

        print(f"Preparing demo trade: {plan.symbol} {plan.direction} size={plan.size}")
        epic = ig_service.search_market(plan.search_term)
        if not epic:
            message = "Could not find a tradable IG market for this search term."
            print(f"{plan.symbol}: {message}")
            log_demo_order(
                timestamp=datetime.now(),
                symbol=plan.symbol,
                epic="",
                direction=plan.direction,
                size=plan.size,
                status="FAILED",
                message=message,
            )
            continue

        result = ig_service.place_demo_market_order(
            epic=epic,
            direction=plan.direction,
            size=plan.size,
        )

        status = "SENT" if result.get("success") else "FAILED"
        message = result.get("message", "")
        deal_reference = result.get("deal_reference", "")
        deal_id = result.get("deal_id", "")

        log_demo_order(
            timestamp=datetime.now(),
            symbol=plan.symbol,
            epic=epic,
            direction=plan.direction,
            size=plan.size,
            status=status,
            deal_reference=deal_reference,
            deal_id=deal_id,
            message=message,
        )
        log_event(
            timestamp=datetime.now(),
            symbol=plan.symbol,
            event="DEMO_ORDER_" + status,
            paper_action=f"{plan.direction} demo order",
            notes=message,
        )

        print(f"{plan.symbol}: demo order {status}. {message}")
        if deal_reference:
            print(f"{plan.symbol}: deal reference {deal_reference}")

        if result.get("success"):
            trades_sent += 1


def place_demo_order_from_signal(ig_service, signal_info):
    if not AUTO_SIGNAL_DEMO_TRADING:
        return False

    # Check maximum drawdown
    if _is_max_drawdown_reached():
        print("Maximum drawdown reached. Skipping demo order.")
        return False

    symbol = signal_info["symbol"]
    signal = signal_info["signal"]
    quality = signal_info.get("quality", 0)
    current_price = signal_info["current_price"]

    # Filter low quality signals
    if quality < MIN_SIGNAL_QUALITY:
        print(f"{symbol}: Signal quality too low ({quality:.2f}). Skipping demo order.")
        return False

    direction = demo_direction_for_signal(signal)

    if not direction:
        return False

    if _already_traded_today(symbol):
        print(f"{symbol}: signal demo trade already sent today. Skipping.")
        return False

    size = _calculate_demo_size(current_price)
    if size is None:
        message = "Could not calculate demo size from current price."
        print(f"{symbol}: {message}")
        log_demo_order(
            timestamp=datetime.now(),
            symbol=symbol,
            epic="",
            direction=direction,
            size="",
            status="SIGNAL_FAILED",
            message=message,
        )
        return False

    search_term = IG_SEARCH_MAP.get(symbol, symbol)
    print(
        f"{symbol}: auto signal demo order candidate | "
        f"signal={signal} | direction={direction} | approx ${SIGNAL_DEMO_NOTIONAL_USD} | size={size}"
    )

    epic = ig_service.search_market(search_term)
    if not epic:
        message = "Could not find IG market for signal demo order."
        print(f"{symbol}: {message}")
        log_demo_order(
            timestamp=datetime.now(),
            symbol=symbol,
            epic="",
            direction=direction,
            size=size,
            status="SIGNAL_FAILED",
            message=message,
        )
        return False

    result = ig_service.place_demo_market_order(
        epic=epic,
        direction=direction,
        size=size,
    )

    status = "SIGNAL_SENT" if result.get("success") else "SIGNAL_FAILED"
    message = result.get("message", "")
    deal_reference = result.get("deal_reference", "")
    deal_id = result.get("deal_id", "")

    log_demo_order(
        timestamp=datetime.now(),
        symbol=symbol,
        epic=epic,
        direction=direction,
        size=size,
        status=status,
        deal_reference=deal_reference,
        deal_id=deal_id,
        message=message,
    )
    log_event(
        timestamp=datetime.now(),
        symbol=symbol,
        event="AUTO_SIGNAL_DEMO_ORDER_" + status,
        base_price=signal_info["base_price"],
        current_price=current_price,
        change_percent=signal_info["change_percent"],
        signal=signal,
        paper_action=f"{direction} demo order from signal",
        notes=message,
    )

    print(f"{symbol}: auto signal demo order {status}. {message}")
    if deal_reference:
        print(f"{symbol}: deal reference {deal_reference}")

    return result.get("success", False)


def place_top_signal_orders(ig_service, signal_candidates):
    if not AUTO_SIGNAL_DEMO_TRADING:
        return 0

    if not signal_candidates:
        return 0

    ranked_candidates = _rank_signal_candidates(signal_candidates)
    if not ranked_candidates:
        print("No eligible prediction candidates for auto signal orders.")
        return 0

    selected = ranked_candidates[:MAX_SIGNAL_DEMO_TRADES_PER_ROUND]
    checked_count = min(len(signal_candidates), SIGNAL_CANDIDATE_POOL_SIZE)
    print(f"Selected {len(selected)} prediction candidate(s) from {checked_count} checked symbol(s).")

    orders_sent = 0
    for candidate in selected:
        if place_demo_order_from_signal(ig_service, candidate):
            orders_sent += 1

    return orders_sent


def _rank_signal_candidates(signal_candidates):
    limited_candidates = signal_candidates[:SIGNAL_CANDIDATE_POOL_SIZE]
    eligible = []

    for candidate in limited_candidates:
        signal = candidate.get("signal")
        direction = demo_direction_for_signal(signal)
        quality = _to_float(candidate.get("quality")) or 0.0

        if not direction:
            continue

        if quality < MIN_SIGNAL_QUALITY:
            continue

        eligible.append(candidate)

    return sorted(
        eligible,
        key=lambda item: (
            item.get("quality", 0),
            signal_score(item.get("signal"), item.get("change_percent", 0))[0],
            signal_score(item.get("signal"), item.get("change_percent", 0))[1],
        ),
        reverse=True,
    )


def _already_traded_today(symbol):
    if not DEMO_TRADE_ONCE_PER_SYMBOL_PER_DAY:
        return False

    if not DEMO_ORDERS_FILE.exists():
        return False

    today = datetime.now().date().isoformat()
    valid_open_statuses = {"SENT", "SIGNAL_SENT"}

    with DEMO_ORDERS_FILE.open("r", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            row_symbol = (row.get("symbol") or "").strip().upper()
            status = (row.get("status") or "").strip().upper()
            timestamp = row.get("timestamp") or ""

            if (
                row_symbol == symbol
                and status in valid_open_statuses
                and timestamp.startswith(today)
            ):
                return True

    return False


def _is_max_drawdown_reached():
    if not CLOSED_POSITIONS_FILE.exists():
        return False

    total_pl = 0.0
    with CLOSED_POSITIONS_FILE.open("r", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            pl = float(row.get('profit_loss', 0))
            total_pl += pl

    return total_pl <= MAX_DRAWDOWN


def _calculate_demo_size(current_price):
    price = _to_float(current_price)
    if price is None or price <= 0:
        return None

    size = SIGNAL_DEMO_NOTIONAL_USD / price
    return round(max(size, 0.00001), 5)


def print_open_positions(ig_service):
    positions = ig_service.get_open_positions()
    if positions is None:
        message = (
            f"IG unavailable as of {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: "
            "using last known open position snapshots."
        )
        print(f"⚠ {message}")
        set_dashboard_status("ig_status", message)
        return

    set_dashboard_status("ig_status", "")

    if not positions:
        print("Open demo positions: none")
        write_open_positions([])
        return

    print(f"Open demo positions: {len(positions)}")
    open_rows = []
    for item in positions:
        market = item.get("market", {})
        position = item.get("position", {})
        instrument = market.get("instrumentName", "Unknown")
        epic = market.get("epic", "")
        direction = position.get("direction", "")
        size = _to_float(position.get("size"))
        open_level = _to_float(position.get("level"))
        deal_id = position.get("dealId", "")
        currency = position.get("currency", "")

        current_price = _get_position_current_price(ig_service, epic, direction)
        profit_loss = _extract_profit_loss(item)
        if profit_loss is None:
            profit_loss = _estimate_profit_loss(
                direction=direction,
                size=size,
                open_level=open_level,
                current_price=current_price,
            )

        profit_loss_text = _format_money(profit_loss, currency)
        current_price_text = current_price if current_price is not None else "unavailable"

        print(
            f"{instrument} | {direction} | size={size} | "
            f"open={open_level} | current={current_price_text} | "
            f"P/L={profit_loss_text}"
        )

        snapshot_row = {
            "timestamp": datetime.now(),
            "instrument": instrument,
            "epic": epic,
            "direction": direction,
            "size": size,
            "open_level": open_level,
            "current_price": current_price if current_price is not None else "",
            "profit_loss": profit_loss if profit_loss is not None else "",
            "currency": currency,
            "deal_id": deal_id,
        }
        open_rows.append(snapshot_row)

        log_position_snapshot(
            timestamp=snapshot_row["timestamp"],
            instrument=instrument,
            epic=epic,
            direction=direction,
            size=size,
            open_level=open_level,
            current_price=current_price if current_price is not None else "",
            profit_loss=profit_loss if profit_loss is not None else "",
            currency=currency,
            deal_id=deal_id,
        )

        _auto_close_if_needed(
            ig_service=ig_service,
            instrument=instrument,
            deal_id=deal_id,
            direction=direction,
            size=size,
            profit_loss=profit_loss,
            snapshot_row=snapshot_row,
        )

    write_open_positions(open_rows)


def _auto_close_if_needed(
    ig_service,
    instrument,
    deal_id,
    direction,
    size,
    profit_loss,
    snapshot_row,
):
    if not AUTO_CLOSE_DEMO_POSITIONS:
        return

    if not deal_id:
        return

    if deal_id in CLOSE_ORDERS_SENT:
        return

    if profit_loss is None:
        return

    should_close = profit_loss >= DEMO_TAKE_PROFIT_AMOUNT or profit_loss <= -DEMO_STOP_LOSS_AMOUNT
    if not should_close:
        return

    reason = "TAKE_PROFIT" if profit_loss >= DEMO_TAKE_PROFIT_AMOUNT else "STOP_LOSS"
    print(f"{instrument} | {reason} hit at P/L={profit_loss}. Sending demo close order...")

    result = ig_service.close_demo_position(
        deal_id=deal_id,
        direction=direction,
        size=size,
    )

    status = "SENT" if result.get("success") else "FAILED"
    message = result.get("message", "")
    close_reference = result.get("deal_reference", "")

    CLOSE_ORDERS_SENT.add(deal_id)
    log_demo_order(
        timestamp=datetime.now(),
        symbol=instrument,
        epic="",
        direction="CLOSE",
        size=size,
        status=f"{reason}_{status}",
        deal_reference=close_reference,
        deal_id=deal_id,
        message=message,
    )
    log_event(
        timestamp=datetime.now(),
        symbol=instrument,
        event=f"DEMO_AUTO_CLOSE_{reason}_{status}",
        paper_action="Close demo position",
        notes=f"P/L={profit_loss}. {message}",
    )

    closed_row = dict(snapshot_row)
    closed_row["timestamp"] = datetime.now()
    log_closed_position(closed_row)

    print(f"{instrument} | auto close {status}. {message}")


def _get_position_current_price(ig_service, epic, direction):
    if not epic:
        return None

    price = ig_service.get_price(epic)
    if price is not None:
        return price

    return None


def _extract_profit_loss(position_item):
    possible_keys = [
        "profit",
        "profitLoss",
        "upl",
    ]

    for container in [position_item, position_item.get("position", {})]:
        for key in possible_keys:
            value = container.get(key)
            number = _to_float(value)
            if number is not None:
                return number

    return None


def _estimate_profit_loss(direction, size, open_level, current_price):
    if size is None or open_level is None or current_price is None:
        return None

    if direction == "BUY":
        return round((current_price - open_level) * size, 5)
    if direction == "SELL":
        return round((open_level - current_price) * size, 5)

    return None


def _to_float(value):
    if value in [None, ""]:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_money(value, currency):
    if value is None:
        return "unavailable"

    if currency:
        return f"{round(value, 5)} {currency}"

    return str(round(value, 5))
