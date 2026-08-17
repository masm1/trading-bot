# -*- coding: utf-8 -*-
import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

from config import (
    AUTO_ADD_IPOS,
    AUTO_ADD_SEED_SYMBOLS,
    AUTO_DISCOVERY_ENABLED,
    AUTO_DISCOVERY_LOOKAHEAD_DAYS,
    AUTO_DISCOVERY_LOOKBACK_DAYS,
    AUTO_DISCOVERY_OUTPUT_FILE,
    AUTO_DISCOVERY_REFRESH_HOURS,
    DISCOVERY_EXTRA_SYMBOLS,
    DISCOVERY_SEED_SYMBOLS,
    FINNHUB_API_KEY,
    LIVE_TREND_SYMBOLS,
    MAX_AUTO_WATCHLIST_SYMBOLS,
    MAX_IPO_SYMBOLS,
    MIN_DISCOVERY_PRICE,
    looks_like_placeholder,
)
from mapping import EPIC_MAP

PROJECT_DIR = Path(__file__).resolve().parent
AUTO_WATCHLIST_FILE = PROJECT_DIR / AUTO_DISCOVERY_OUTPUT_FILE
DISCOVERY_STATE_FILE = PROJECT_DIR / "market_discovery_state.json"
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FIELDNAMES = [
    "symbol",
    "active",
    "notes",
    "name",
    "source",
    "category",
    "score",
    "reason",
    "last_updated",
    "ipo_date",
    "ipo_status",
    "exchange",
    "price",
]


def refresh_auto_watchlist_if_due(force=False):
    if not AUTO_DISCOVERY_ENABLED:
        return discovery_snapshot("Auto discovery disabled.")

    if not force and not _is_refresh_due():
        return discovery_snapshot("Using cached discovery list.")

    return refresh_auto_watchlist()


def refresh_auto_watchlist():
    now = datetime.now(timezone.utc)
    candidates = []
    rejected = []

    if AUTO_ADD_SEED_SYMBOLS:
        for symbol, label in _configured_symbols(DISCOVERY_SEED_SYMBOLS):
            candidates.append(
                _candidate(
                    symbol=symbol,
                    name=label,
                    source="seed",
                    category="market",
                    score=95,
                    reason="Configured discovery seed.",
                    now=now,
                )
            )

        for symbol, label in _configured_symbols(LIVE_TREND_SYMBOLS):
            candidates.append(
                _candidate(
                    symbol=symbol,
                    name=label,
                    source="trend_seed",
                    category="live_trend",
                    score=92,
                    reason="Configured live trend auto-buy seed.",
                    now=now,
                )
            )

    for symbol, label in _configured_symbols(DISCOVERY_EXTRA_SYMBOLS):
        candidates.append(
            _candidate(
                symbol=symbol,
                name=label,
                source="manual_seed",
                category="market",
                score=80,
                reason="Configured extra discovery symbol.",
                now=now,
            )
        )

    if AUTO_ADD_IPOS:
        ipo_rows, ipo_rejections = _discover_ipos(now)
        candidates.extend(ipo_rows)
        rejected.extend(ipo_rejections)

    accepted, rejected_by_rules = _select_active_candidates(candidates)
    rejected.extend(rejected_by_rules)
    all_rows = accepted + rejected
    _write_watchlist(all_rows)
    _write_state(now=now, accepted=accepted, rejected=rejected)
    return discovery_snapshot("Discovery refreshed.")


def discovery_snapshot(message=""):
    rows = _read_watchlist()
    active = [row for row in rows if _truthy(row.get("active"))]
    skipped = [row for row in rows if not _truthy(row.get("active"))]
    state = _read_state()

    return {
        "enabled": AUTO_DISCOVERY_ENABLED,
        "message": message or state.get("message", ""),
        "last_refresh": state.get("last_refresh", ""),
        "next_refresh": state.get("next_refresh", ""),
        "active_count": len(active),
        "skipped_count": len(skipped),
        "max_symbols": MAX_AUTO_WATCHLIST_SYMBOLS,
        "max_ipo_symbols": MAX_IPO_SYMBOLS,
        "min_price": MIN_DISCOVERY_PRICE,
        "rows": rows[:50],
        "active_symbols": [row.get("symbol", "") for row in active],
    }


def _discover_ipos(now):
    if requests is None:
        return [], [_rejected("IPO", "requests missing", "ipo", "upcoming", "requests is not installed.", now)]

    if looks_like_placeholder(FINNHUB_API_KEY):
        return [], [_rejected("IPO", "Finnhub key missing", "ipo", "upcoming", "FINNHUB_API_KEY is not configured.", now)]

    start = (now.date() - timedelta(days=AUTO_DISCOVERY_LOOKBACK_DAYS)).isoformat()
    end = (now.date() + timedelta(days=AUTO_DISCOVERY_LOOKAHEAD_DAYS)).isoformat()

    try:
        response = requests.get(
            f"{FINNHUB_BASE_URL}/calendar/ipo",
            params={"from": start, "to": end, "token": FINNHUB_API_KEY},
            timeout=10,
        )
        if response.status_code != 200:
            return [], [_rejected("IPO", "Finnhub IPO calendar", "ipo", "upcoming", f"Finnhub HTTP {response.status_code}.", now)]

        items = response.json().get("ipoCalendar") or []
    except Exception as exc:
        return [], [_rejected("IPO", "Finnhub IPO calendar", "ipo", "upcoming", f"IPO calendar unavailable: {exc}", now)]

    rows = []
    rejected = []
    for item in items:
        symbol = (item.get("symbol") or "").strip().upper()
        name = (item.get("name") or symbol).strip()
        status = (item.get("status") or "").strip().lower()
        ipo_date = (item.get("date") or "").strip()
        exchange = (item.get("exchange") or "").strip()

        if not symbol:
            continue

        row = _candidate(
            symbol=symbol,
            name=name,
            source="ipo",
            category=status or "ipo",
            score=_ipo_score(ipo_date, status, now.date()),
            reason=f"IPO {status or 'calendar'} from Finnhub.",
            now=now,
            ipo_date=ipo_date,
            ipo_status=status,
            exchange=exchange,
        )

        if status in {"expected", "filed"}:
            row["active"] = "no"
            row["reason"] = "Upcoming IPO found; waiting for live quote before trading."
            rejected.append(row)
            continue

        rows.append(row)

    rows.sort(key=lambda row: _to_float(row.get("score")) or 0, reverse=True)
    kept = rows[:MAX_IPO_SYMBOLS]
    for row in rows[MAX_IPO_SYMBOLS:]:
        row["active"] = "no"
        row["reason"] = f"IPO limit reached: MAX_IPO_SYMBOLS={MAX_IPO_SYMBOLS}."
        rejected.append(row)
    return kept, rejected


def _select_active_candidates(candidates):
    deduped = {}
    for row in candidates:
        symbol = row["symbol"]
        if symbol not in deduped or float(row["score"]) > float(deduped[symbol]["score"]):
            deduped[symbol] = row

    accepted = []
    rejected = []
    for row in sorted(deduped.values(), key=lambda item: _to_float(item.get("score")) or 0, reverse=True):
        if row["symbol"] not in EPIC_MAP:
            row["active"] = "no"
            row["reason"] = f"{row['reason']} No confirmed IG route for auto-buy."
            rejected.append(row)
            continue

        if row.get("source") in {"seed", "trend_seed", "manual_seed"}:
            row["active"] = "yes"
            row["reason"] = f"{row['reason']} Kept active by configuration."
            accepted.append(row)
            continue

        quote = _quote(row["symbol"])
        price = quote.get("price")
        if price is not None:
            row["price"] = f"{price:.2f}"

        if len(accepted) >= MAX_AUTO_WATCHLIST_SYMBOLS:
            row["active"] = "no"
            row["reason"] = f"Auto watchlist limit reached: MAX_AUTO_WATCHLIST_SYMBOLS={MAX_AUTO_WATCHLIST_SYMBOLS}."
            rejected.append(row)
            continue

        if price is None:
            row["active"] = "no"
            row["reason"] = quote.get("message", "No live quote available.")
            rejected.append(row)
            continue

        if price < MIN_DISCOVERY_PRICE:
            row["active"] = "no"
            row["reason"] = f"Price ${price:.2f} is below MIN_DISCOVERY_PRICE=${MIN_DISCOVERY_PRICE:g}."
            rejected.append(row)
            continue

        row["active"] = "yes"
        row["reason"] = f"{row['reason']} Quote passed at ${price:.2f}."
        accepted.append(row)

    return accepted, rejected


def _quote(symbol):
    if requests is None:
        return {"price": None, "message": "requests is not installed."}

    if looks_like_placeholder(FINNHUB_API_KEY):
        return {"price": None, "message": "FINNHUB_API_KEY is not configured."}

    try:
        response = requests.get(
            f"{FINNHUB_BASE_URL}/quote",
            params={"symbol": symbol.upper(), "token": FINNHUB_API_KEY},
            timeout=8,
        )
        if response.status_code != 200:
            return {"price": None, "message": f"Quote HTTP {response.status_code}."}

        data = response.json()
        price = _to_float(data.get("c") or data.get("pc"))
        if price is None or price <= 0:
            return {"price": None, "message": "No usable quote returned."}
        return {"price": price, "message": ""}
    except Exception as exc:
        return {"price": None, "message": f"Quote unavailable: {exc}"}


def _candidate(symbol, name, source, category, score, reason, now, ipo_date="", ipo_status="", exchange="", active="yes"):
    return {
        "symbol": symbol.strip().upper(),
        "active": active,
        "notes": reason,
        "name": name.strip(),
        "source": source,
        "category": category,
        "score": str(round(score, 2)),
        "reason": reason,
        "last_updated": now.isoformat(sep=" ", timespec="seconds"),
        "ipo_date": ipo_date,
        "ipo_status": ipo_status,
        "exchange": exchange,
        "price": "",
    }


def _rejected(symbol, name, source, category, reason, now):
    return _candidate(symbol, name, source, category, 0, reason, now, active="no")


def _configured_symbols(value):
    rows = []
    for item in (value or "").split(","):
        item = item.strip()
        if not item:
            continue

        symbol, _, label = item.partition(":")
        symbol = symbol.strip().upper()
        label = label.strip() or symbol
        if symbol:
            rows.append((symbol, label))
    return rows


def _ipo_score(ipo_date, status, today):
    score = 70
    parsed = _parse_date(ipo_date)
    if parsed:
        days = abs((parsed - today).days)
        score += max(0, 20 - days)
    if status == "priced":
        score += 10
    return score


def _is_refresh_due():
    state = _read_state()
    last_refresh = _parse_datetime(state.get("last_refresh"))
    if not AUTO_WATCHLIST_FILE.exists() or not last_refresh:
        return True

    return datetime.now(timezone.utc) - last_refresh >= timedelta(hours=AUTO_DISCOVERY_REFRESH_HOURS)


def _write_watchlist(rows):
    with AUTO_WATCHLIST_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})


def _read_watchlist():
    if not AUTO_WATCHLIST_FILE.exists():
        return []

    with AUTO_WATCHLIST_FILE.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return [row for row in reader if row.get("symbol")]


def _write_state(now, accepted, rejected):
    next_refresh = now + timedelta(hours=AUTO_DISCOVERY_REFRESH_HOURS)
    state = {
        "message": "Discovery refreshed.",
        "last_refresh": now.isoformat(sep=" ", timespec="seconds"),
        "next_refresh": next_refresh.isoformat(sep=" ", timespec="seconds"),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
    }
    DISCOVERY_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _read_state():
    if not DISCOVERY_STATE_FILE.exists():
        return {}

    try:
        return json.loads(DISCOVERY_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value):
    return str(value or "").strip().lower() in {"yes", "y", "true", "1", "active"}


if __name__ == "__main__":
    snapshot = refresh_auto_watchlist()
    print(f"Active symbols: {', '.join(snapshot['active_symbols'])}")
