import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"


def load_env_file():
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_FILE)
        return
    except ImportError:
        pass

    if not ENV_FILE.exists():
        return

    for line in ENV_FILE.read_text().splitlines():
        clean_line = line.strip()
        if not clean_line or clean_line.startswith("#") or "=" not in clean_line:
            continue

        name, value = clean_line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


load_env_file()


def get_env(name, default=None):
    value = os.getenv(name, default)
    if value is None:
        return None
    return value.strip()


def looks_like_placeholder(value):
    if not value:
        return True

    lower_value = value.lower()
    placeholder_words = [
        "your_",
        "put_your",
        "paste_",
        "_here",
    ]
    return any(word in lower_value for word in placeholder_words)


IG_API_KEY = get_env("IG_API_KEY")
IG_USERNAME = get_env("IG_USERNAME")
IG_PASSWORD = get_env("IG_PASSWORD")
IG_BASE_URL = get_env("IG_BASE_URL", "https://demo-api.ig.com/gateway/deal").rstrip("/")
FINNHUB_API_KEY = get_env("FINNHUB_API_KEY")
PAPER_TRADING = get_env("PAPER_TRADING", "true").lower() == "true"
AUTO_DEMO_TRADING = get_env("AUTO_DEMO_TRADING", "false").lower() == "true"
MAX_DEMO_TRADES_PER_RUN = int(get_env("MAX_DEMO_TRADES_PER_RUN", "1"))
DEMO_TRADE_ONCE_PER_SYMBOL_PER_DAY = (
    get_env("DEMO_TRADE_ONCE_PER_SYMBOL_PER_DAY", "true").lower() == "true"
)
AUTO_CLOSE_DEMO_POSITIONS = get_env("AUTO_CLOSE_DEMO_POSITIONS", "true").lower() == "true"
DEMO_TAKE_PROFIT_AMOUNT = float(get_env("DEMO_TAKE_PROFIT_AMOUNT", "2500"))
DEMO_STOP_LOSS_AMOUNT = float(get_env("DEMO_STOP_LOSS_AMOUNT", "700"))
CONTINUOUS_PRICE_MONITORING = get_env("CONTINUOUS_PRICE_MONITORING", "true").lower() == "true"
AUTO_SIGNAL_DEMO_TRADING = get_env("AUTO_SIGNAL_DEMO_TRADING", "false").lower() == "true"
SIGNAL_DEMO_NOTIONAL_USD = float(get_env("SIGNAL_DEMO_NOTIONAL_USD", "500"))
MAX_SIGNAL_DEMO_TRADES_PER_ROUND = int(get_env("MAX_SIGNAL_DEMO_TRADES_PER_ROUND", "3"))
SIGNAL_CANDIDATE_POOL_SIZE = int(get_env("SIGNAL_CANDIDATE_POOL_SIZE", "10"))
MIN_SIGNAL_QUALITY = float(get_env("MIN_SIGNAL_QUALITY", "0.6"))
CALL_SIGNAL_THRESHOLD_PERCENT = float(get_env("CALL_SIGNAL_THRESHOLD_PERCENT", "1.0"))
PUT_SIGNAL_THRESHOLD_PERCENT = float(get_env("PUT_SIGNAL_THRESHOLD_PERCENT", "-1.0"))
FADE_SIGNAL_THRESHOLD_PERCENT = float(get_env("FADE_SIGNAL_THRESHOLD_PERCENT", "0.25"))
MAX_DRAWDOWN = float(get_env("MAX_DRAWDOWN", "-1000"))
MARKET_OPEN_AUTO_MODE = get_env("MARKET_OPEN_AUTO_MODE", "false").lower() == "true"
MARKET_OPEN_WATCHLIST_FILE = get_env("MARKET_OPEN_WATCHLIST_FILE", "market_open_watchlist.csv")
MARKET_OPEN_TIME = get_env("MARKET_OPEN_TIME", "09:30")
MARKET_OPEN_TIMEZONE = get_env("MARKET_OPEN_TIMEZONE", "America/New_York")
MARKET_OPEN_BASE_MINUTES = int(get_env("MARKET_OPEN_BASE_MINUTES", "5"))
MARKET_OPEN_CHECK_START_MINUTES = int(get_env("MARKET_OPEN_CHECK_START_MINUTES", "15"))
MARKET_OPEN_CHECK_END_MINUTES = int(get_env("MARKET_OPEN_CHECK_END_MINUTES", "90"))
