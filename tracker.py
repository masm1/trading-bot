from datetime import datetime

from logger import log_event, log_paper_trade
from mapping import EPIC_MAP, PRICE_SYMBOL_MAP
from strategy import detect_signal, paper_action_for_signal


class PriceTracker:
    def __init__(self, ig_service):
        self.ig = ig_service
        self.base_prices = {}
        self.failed_symbols = {}
        self.logged_signals = set()

    # ---------------- BASE PRICE ---------------- #
    def save_base_price(self, symbol):
        epic = EPIC_MAP.get(symbol)

        price = self.ig.get_price_for_symbol(symbol, epic)

        if price is None:
            print(f"⚠ Could not get base price for {symbol}")

            log_event(
                timestamp=datetime.now(),
                symbol=symbol,
                event="BASE_PRICE_FAILED",
                notes="No price available",
            )
            return None

        self.base_prices[symbol] = price

        print(f"{datetime.now()} | BASE SAVED | {symbol} | {price}")

        log_event(
            timestamp=datetime.now(),
            symbol=symbol,
            event="BASE_PRICE_SAVED",
            base_price=price,
        )

        return price

    # ---------------- SIGNAL CHECK ---------------- #
    def check_signal(self, symbol):
        epic = EPIC_MAP.get(symbol)

        base_price = self.base_prices.get(symbol)

        if base_price is None:
            print(f"{symbol}: No base price → saving first")
            self.save_base_price(symbol)
            return None

        current_price = self.ig.get_price_for_symbol(symbol, epic)

        # 🔥 CRITICAL FIX: Always log even if no price
        if current_price is None:
            print(f"⚠ No price for {symbol}")

            log_event(
                timestamp=datetime.now(),
                symbol=symbol,
                event="NO_PRICE",
                base_price=base_price,
                notes="Skipped due to missing price",
            )
            return None

        # ---------------- SIGNAL ---------------- #
        result = detect_signal(base_price, current_price)
        paper_action = paper_action_for_signal(result)

        print(
            f"{datetime.now()} | {symbol} | base={base_price} | "
            f"current={current_price} | change={result['change_percent']}% | "
            f"signal={result['signal']} | quality={result.get('quality', 0)}"
        )

        # 🔥 ALWAYS LOG
        log_event(
            timestamp=datetime.now(),
            symbol=symbol,
            event="SIGNAL_CHECK",
            base_price=base_price,
            current_price=current_price,
            change_percent=result["change_percent"],
            signal=result["signal"],
            paper_action=paper_action,
        )

        if result["signal"] != "NO_SIGNAL":
            log_paper_trade(
                timestamp=datetime.now(),
                symbol=symbol,
                signal=result["signal"],
                paper_action=paper_action,
                base_price=base_price,
                current_price=current_price,
                change_percent=result["change_percent"],
                notes=f"Paper trade idea only. Quality: {result.get('quality', 0):.2f}",
            )

        # ---------------- DEMO ORDER ---------------- #
        signal_info = {
            "symbol": symbol,
            "signal": result["signal"],
            "base_price": base_price,
            "current_price": current_price,
            "change_percent": result["change_percent"],
            "quality": result.get("quality", 0),
        }

        return signal_info
