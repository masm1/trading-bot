import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone

PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "trading.db"
DB_LOCK = threading.Lock()


def _connect_db():
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    with DB_LOCK, _connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT,
                event TEXT,
                base_price REAL,
                current_price REAL,
                change_percent REAL,
                signal TEXT,
                paper_action TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT,
                signal TEXT,
                paper_action TEXT,
                base_price REAL,
                current_price REAL,
                change_percent REAL,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS demo_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT,
                epic TEXT,
                direction TEXT,
                size REAL,
                status TEXT,
                deal_reference TEXT,
                deal_id TEXT,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS positions_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                instrument TEXT,
                epic TEXT,
                direction TEXT,
                size REAL,
                open_level REAL,
                current_price REAL,
                profit_loss REAL,
                currency TEXT,
                deal_id TEXT
            );

            CREATE TABLE IF NOT EXISTS open_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                instrument TEXT,
                epic TEXT,
                direction TEXT,
                size REAL,
                open_level REAL,
                current_price REAL,
                profit_loss REAL,
                currency TEXT,
                deal_id TEXT
            );

            CREATE TABLE IF NOT EXISTS closed_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                instrument TEXT,
                epic TEXT,
                direction TEXT,
                size REAL,
                open_level REAL,
                current_price REAL,
                profit_loss REAL,
                currency TEXT,
                deal_id TEXT
            );

            CREATE TABLE IF NOT EXISTS dashboard_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                value TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )


def _normalize_timestamp(value):
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat(sep=" ", timespec="seconds")

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat(sep=" ", timespec="seconds")
        except (ValueError, TypeError):
            return value.strip()

    return str(value)


def insert_row(table, row):
    init_db()
    keys = [key for key in row.keys() if row[key] is not None]
    placeholders = ", ".join("?" for _ in keys)
    columns = ", ".join(keys)
    values = [row[key] for key in keys]

    with DB_LOCK, _connect_db() as conn:
        conn.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            values,
        )
        conn.commit()


def replace_rows(table, rows):
    init_db()
    with DB_LOCK, _connect_db() as conn:
        conn.execute(f"DELETE FROM {table}")
        if not rows:
            conn.commit()
            return

        keys = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in keys)
        columns = ", ".join(keys)
        values = [[row.get(key) for key in keys] for row in rows]
        conn.executemany(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            values,
        )
        conn.commit()


def fetch_latest_rows(table, limit=25):
    init_db()
    with DB_LOCK, _connect_db() as conn:
        cursor = conn.execute(
            f"SELECT * FROM {table} ORDER BY datetime(timestamp) DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    return rows[::-1]


def fetch_row_count(table):
    init_db()
    with DB_LOCK, _connect_db() as conn:
        cursor = conn.execute(f"SELECT COUNT(*) AS count FROM {table}")
        return cursor.fetchone()[0]


def get_last_update(table="trade_log"):
    init_db()
    with DB_LOCK, _connect_db() as conn:
        cursor = conn.execute(
            f"SELECT MAX(timestamp) AS last_update FROM {table}"
        )
        result = cursor.fetchone()
    return result[0] if result else None


def upsert_status(name, value):
    init_db()
    updated_at = _normalize_timestamp(datetime.now(timezone.utc))
    with DB_LOCK, _connect_db() as conn:
        conn.execute(
            "REPLACE INTO dashboard_status (name, value, updated_at) VALUES (?, ?, ?)",
            (name, value, updated_at),
        )
        conn.commit()


def fetch_status(name):
    init_db()
    with DB_LOCK, _connect_db() as conn:
        cursor = conn.execute(
            "SELECT value FROM dashboard_status WHERE name = ?",
            (name,),
        )
        result = cursor.fetchone()
    return result[0] if result else None
