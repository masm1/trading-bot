from datetime import datetime
from logger import log_paper_trade, create_log_files_if_missing


def insert_test_row(symbol="TSLA", signal="STRONG_RALLY", base_price=400, current_price=406, change_percent=1.5):
    create_log_files_if_missing()
    log_paper_trade(
        timestamp=datetime.now(),
        symbol=symbol,
        signal=signal,
        paper_action="TEST_INSERT",
        base_price=base_price,
        current_price=current_price,
        change_percent=change_percent,
        notes="Inserted by automated helper",
    )
    print(f"Inserted test paper trade for {symbol}")


if __name__ == "__main__":
    insert_test_row()
