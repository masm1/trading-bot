# -*- coding: utf-8 -*-
from ig_service import IGService
from logger import create_log_files_if_missing, log_event
from watchlist import load_watchlist, get_event_stage
from tracker import PriceTracker
from demo_trader import place_top_signal_orders, print_open_positions

from datetime import datetime
import time
import sys
import io

# UTF-8 fix (Windows)
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CYCLE_DELAY = 30
SYMBOL_DELAY = 2


def main():
    print("🚀 Starting Trading Bot...\n")
    create_log_files_if_missing()

    ig = IGService()

    # 🔥 Keep login SIMPLE (no retry loops here)
    login_success = ig.login()

    if not login_success:
        print("⚠ IG login failed → continuing with fallback pricing\n")
    else:
        print("✅ Logged in to IG\n")

    tracker = PriceTracker(ig)

    while True:
        try:
            now = datetime.now()
            print(f"\n🔄 Cycle at {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

            watch_items = load_watchlist()

            if not watch_items:
                print("⚠ No active symbols in watchlist")
                time.sleep(CYCLE_DELAY)
                continue

            # ---------------- PROCESS SYMBOLS ---------------- #
            signal_candidates = []
            for item in watch_items:
                symbol = item.symbol
                stage = get_event_stage(item, now)

                print(f"📌 {symbol} | Stage: {stage}")

                if stage == "SAVE_BASE_PRICE":
                    tracker.save_base_price(symbol)

                elif stage.startswith("CHECK"):
                    signal_info = tracker.check_signal(symbol)
                    if signal_info:
                        signal_candidates.append(signal_info)

                time.sleep(SYMBOL_DELAY)

            place_top_signal_orders(ig, signal_candidates)
            log_event(
                timestamp=datetime.now(),
                symbol="SYSTEM",
                event="BOT_CYCLE_COMPLETE",
                notes=f"Watched {len(watch_items)} active symbol(s); checked {len(signal_candidates)} signal candidate(s).",
            )

            # 🔥 Dashboard sync (this was already working before)
            print("\n📊 Updating dashboard...\n")
            try:
                print_open_positions(ig)
            except Exception as e:
                print("⚠ Dashboard refresh skipped due to IG error:", e)

            print("\n⏳ Cycle complete\n")
            time.sleep(CYCLE_DELAY)

        except KeyboardInterrupt:
            print("\n🛑 Stopping bot...")
            break

        except Exception as e:
            print("❌ Runtime error:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
