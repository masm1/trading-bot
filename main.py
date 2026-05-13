# -*- coding: utf-8 -*-
import io
import sys
import time
from datetime import datetime

from config import MARKET_OPEN_AUTO_MODE
from demo_trader import place_top_signal_orders, print_open_positions
from ig_service import IGService
from logger import create_log_files_if_missing, log_event
from market_open import (
    describe_market_open_clock,
    get_market_open_stage,
    load_market_open_watchlist,
)
from tracker import PriceTracker
from watchlist import get_event_stage, load_watchlist

# UTF-8 fix (Windows)
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

CYCLE_DELAY = 30
SYMBOL_DELAY = 2


def run_earnings_cycle(tracker, now):
    watch_items = load_watchlist()

    if not watch_items:
        print("No active symbols in earnings watchlist")
        return []

    signal_candidates = []
    for item in watch_items:
        symbol = item.symbol
        stage = get_event_stage(item, now)

        print(f"{symbol} | Stage: {stage}")

        if stage == "SAVE_BASE_PRICE":
            tracker.save_base_price(symbol)

        elif stage.startswith("CHECK"):
            signal_info = tracker.check_signal(symbol)
            if signal_info:
                signal_candidates.append(signal_info)

        time.sleep(SYMBOL_DELAY)

    return signal_candidates


def run_market_open_cycle(tracker, now):
    watch_items = load_market_open_watchlist()

    if not watch_items:
        print("No active symbols in market open watchlist")
        return []

    stage = get_market_open_stage(now)
    print(f"Market-open mode | Market clock: {describe_market_open_clock(now)} | Stage: {stage}")

    signal_candidates = []
    for item in watch_items:
        symbol = item.symbol
        print(f"{symbol} | Stage: {stage}")

        if stage == "SAVE_BASE_PRICE":
            tracker.save_base_price(symbol)

        elif stage == "CHECK_MARKET_OPEN_SIGNAL":
            signal_info = tracker.check_signal(symbol)
            if signal_info:
                signal_candidates.append(signal_info)

        time.sleep(SYMBOL_DELAY)

    return signal_candidates


def main():
    print("Starting Trading Bot...\n")
    create_log_files_if_missing()

    ig = IGService()
    login_success = ig.login()

    if not login_success:
        print("IG login failed; continuing with fallback pricing\n")
    else:
        print("Logged in to IG\n")

    tracker = PriceTracker(ig)

    while True:
        try:
            now = datetime.now()
            print(f"\nCycle at {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

            if MARKET_OPEN_AUTO_MODE:
                signal_candidates = run_market_open_cycle(tracker, now)
            else:
                signal_candidates = run_earnings_cycle(tracker, now)

            place_top_signal_orders(ig, signal_candidates)
            log_event(
                timestamp=datetime.now(),
                symbol="SYSTEM",
                event="BOT_CYCLE_COMPLETE",
                notes=f"Checked {len(signal_candidates)} signal candidate(s).",
            )

            print("\nUpdating dashboard...\n")
            try:
                print_open_positions(ig)
            except Exception as e:
                print("Dashboard refresh skipped due to IG error:", e)

            print("\nCycle complete\n")
            time.sleep(CYCLE_DELAY)

        except KeyboardInterrupt:
            print("\nStopping bot...")
            break

        except Exception as e:
            print("Runtime error:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
