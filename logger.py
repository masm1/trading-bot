import csv
from pathlib import Path
from datetime import datetime, timezone

from db import (
    fetch_latest_rows,
    fetch_row_count,
    get_last_update,
    init_db,
    insert_row,
    replace_rows,
    fetch_status,
    upsert_status,
)

PROJECT_DIR = Path(__file__).resolve().parent
TRADES_LOG_FILE = PROJECT_DIR / "trades_log.csv"
PAPER_TRADES_FILE = PROJECT_DIR / "paper_trades.csv"
DEMO_ORDERS_FILE = PROJECT_DIR / "demo_orders.csv"
POSITIONS_LOG_FILE = PROJECT_DIR / "positions_log.csv"
OPEN_POSITIONS_FILE = PROJECT_DIR / "open_positions.csv"
CLOSED_POSITIONS_FILE = PROJECT_DIR / "closed_positions.csv"

FIELDNAMES = [
    "timestamp",
    "symbol",
    "event",
    "base_price",
    "current_price",
    "change_percent",
    "signal",
    "paper_action",
    "notes",
]

PAPER_TRADE_FIELDNAMES = [
    "timestamp",
    "symbol",
    "signal",
    "paper_action",
    "base_price",
    "current_price",
    "change_percent",
    "notes",
]

DEMO_ORDER_FIELDNAMES = [
    "timestamp",
    "symbol",
    "epic",
    "direction",
    "size",
    "status",
    "deal_reference",
    "deal_id",
    "message",
]

POSITIONS_FIELDNAMES = [
    "timestamp",
    "instrument",
    "epic",
    "direction",
    "size",
    "open_level",
    "current_price",
    "profit_loss",
    "currency",
    "deal_id",
]


def _backup_and_recreate(path, fieldnames):
    backup_path = path.with_name(path.stem + ".invalid" + path.suffix)
    if backup_path.exists():
        backup_path = path.with_name(
            path.stem + ".invalid." + datetime.now().strftime("%Y%m%d%H%M%S") + path.suffix
        )
    path.replace(backup_path)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
    print(f"⚠ {path.name} had an invalid header and was recreated. Old file moved to {backup_path.name}")


def _ensure_csv_file(path, fieldnames):
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
        return

    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        header = next(reader, None)

    if header != fieldnames:
        _backup_and_recreate(path, fieldnames)


def replace_csv_rows(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def format_timestamp(value):
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def normalize_db_timestamp(value):
    return format_timestamp(value)


def _read_csv_rows(path, fieldnames):
    if not path.exists():
        return []

    rows = []
    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != fieldnames:
            return []
        for row in reader:
            if not any(value.strip() if isinstance(value, str) else value for value in row.values()):
                continue
            rows.append({key: (value.strip() if isinstance(value, str) else value) for key, value in row.items()})
    return rows


def _has_valid_csv_header(path, fieldnames):
    if not path.exists():
        return False

    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        header = next(reader, None)

    return header == fieldnames


def _migrate_csv_to_sqlite():
    init_db()

    table_map = [
        ("trade_log", TRADES_LOG_FILE, FIELDNAMES, False),
        ("paper_trades", PAPER_TRADES_FILE, PAPER_TRADE_FIELDNAMES, False),
        ("demo_orders", DEMO_ORDERS_FILE, DEMO_ORDER_FIELDNAMES, False),
        ("positions_log", POSITIONS_LOG_FILE, POSITIONS_FIELDNAMES, False),
        ("open_positions", OPEN_POSITIONS_FILE, POSITIONS_FIELDNAMES, True),
        ("closed_positions", CLOSED_POSITIONS_FILE, POSITIONS_FIELDNAMES, False),
    ]

    for table, path, fieldnames, use_replace in table_map:
        try:
            db_count = fetch_row_count(table)
        except Exception:
            db_count = 0

        csv_rows = _read_csv_rows(path, fieldnames)
        if use_replace and _has_valid_csv_header(path, fieldnames):
            normalized_rows = []
            for row in csv_rows:
                normalized_row = {k: normalize_db_timestamp(v) if k == "timestamp" else v for k, v in row.items()}
                normalized_rows.append(normalized_row)
            replace_rows(table, normalized_rows)
            continue

        if not csv_rows:
            continue

        if db_count >= len(csv_rows):
            continue

        normalized_rows = []
        for row in csv_rows:
            normalized_row = {k: normalize_db_timestamp(v) if k == "timestamp" else v for k, v in row.items()}
            normalized_rows.append(normalized_row)

        if use_replace:
            replace_rows(table, normalized_rows)
        else:
            for row in normalized_rows:
                insert_row(table, row)


def log_event(
    timestamp,
    symbol,
    event,
    base_price="",
    current_price="",
    change_percent="",
    signal="",
    paper_action="",
    notes="",
):
    file_exists = TRADES_LOG_FILE.exists()

    row = {
        "timestamp": normalize_db_timestamp(timestamp),
        "symbol": symbol,
        "event": event,
        "base_price": base_price,
        "current_price": current_price,
        "change_percent": change_percent,
        "signal": signal,
        "paper_action": paper_action,
        "notes": notes,
    }

    insert_row("trade_log", row)

    with TRADES_LOG_FILE.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def log_paper_trade(
    timestamp,
    symbol,
    signal,
    paper_action,
    base_price,
    current_price,
    change_percent,
    notes="",
):
    file_exists = PAPER_TRADES_FILE.exists()

    row = {
        "timestamp": normalize_db_timestamp(timestamp),
        "symbol": symbol,
        "signal": signal,
        "paper_action": paper_action,
        "base_price": base_price,
        "current_price": current_price,
        "change_percent": change_percent,
        "notes": notes,
    }

    insert_row("paper_trades", row)

    with PAPER_TRADES_FILE.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PAPER_TRADE_FIELDNAMES)

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def create_log_files_if_missing():
    init_db()
    _ensure_csv_file(TRADES_LOG_FILE, FIELDNAMES)
    _ensure_csv_file(PAPER_TRADES_FILE, PAPER_TRADE_FIELDNAMES)
    _ensure_csv_file(DEMO_ORDERS_FILE, DEMO_ORDER_FIELDNAMES)
    _ensure_csv_file(POSITIONS_LOG_FILE, POSITIONS_FIELDNAMES)
    _ensure_csv_file(OPEN_POSITIONS_FILE, POSITIONS_FIELDNAMES)
    _ensure_csv_file(CLOSED_POSITIONS_FILE, POSITIONS_FIELDNAMES)
    _migrate_csv_to_sqlite()


def log_demo_order(
    timestamp,
    symbol,
    epic,
    direction,
    size,
    status,
    deal_reference="",
    deal_id="",
    message="",
):
    file_exists = DEMO_ORDERS_FILE.exists()

    row = {
        "timestamp": normalize_db_timestamp(timestamp),
        "symbol": symbol,
        "epic": epic,
        "direction": direction,
        "size": size,
        "status": status,
        "deal_reference": deal_reference,
        "deal_id": deal_id,
        "message": message,
    }

    insert_row("demo_orders", row)

    with DEMO_ORDERS_FILE.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=DEMO_ORDER_FIELDNAMES)

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def log_position_snapshot(
    timestamp,
    instrument,
    epic,
    direction,
    size,
    open_level,
    current_price,
    profit_loss,
    currency,
    deal_id,
):
    file_exists = POSITIONS_LOG_FILE.exists()

    row = {
        "timestamp": normalize_db_timestamp(timestamp),
        "instrument": instrument,
        "epic": epic,
        "direction": direction,
        "size": size,
        "open_level": open_level,
        "current_price": current_price,
        "profit_loss": profit_loss,
        "currency": currency,
        "deal_id": deal_id,
    }

    insert_row("positions_log", row)

    with POSITIONS_LOG_FILE.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=POSITIONS_FIELDNAMES)

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def write_open_positions(rows):
    output_rows = []
    for row in rows:
        output_row = dict(row)
        output_row["timestamp"] = normalize_db_timestamp(output_row.get("timestamp"))
        output_rows.append(output_row)

    replace_rows("open_positions", output_rows)

    with OPEN_POSITIONS_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=POSITIONS_FIELDNAMES)
        writer.writeheader()
        for row in output_rows:
            writer.writerow(row)


def set_dashboard_status(name, value):
    upsert_status(name, value)


def get_dashboard_status(name):
    return fetch_status(name)


def log_closed_position(row):
    file_exists = CLOSED_POSITIONS_FILE.exists()
    output_row = dict(row)
    output_row["timestamp"] = normalize_db_timestamp(output_row.get("timestamp"))

    insert_row("closed_positions", output_row)

    with CLOSED_POSITIONS_FILE.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=POSITIONS_FIELDNAMES)

        if not file_exists:
            writer.writeheader()

        writer.writerow(output_row)
