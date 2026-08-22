from datetime import datetime
import unittest
from unittest.mock import Mock, patch

import main


class MainSignalCycleTests(unittest.TestCase):
    def test_run_signal_cycle_checks_market_open_and_earnings(self):
        tracker = Mock()
        now = datetime(2026, 8, 17, 10, 0)

        with (
            patch.object(main, "get_market_open_stage", return_value="CHECK_MARKET_OPEN_SIGNAL"),
            patch.object(main, "run_market_open_cycle", return_value=[{"symbol": "TSLA"}]) as market_cycle,
            patch.object(main, "run_earnings_cycle", return_value=[{"symbol": "NVDA"}]) as earnings_cycle,
        ):
            candidates, note = main.run_signal_cycle(tracker, now)

        self.assertEqual(candidates, [{"symbol": "TSLA"}, {"symbol": "NVDA"}])
        market_cycle.assert_called_once_with(tracker, now, "CHECK_MARKET_OPEN_SIGNAL")
        earnings_cycle.assert_called_once_with(tracker, now)
        self.assertIn("market-open candidate(s)=1", note)
        self.assertIn("earnings candidate(s)=1", note)


if __name__ == "__main__":
    unittest.main()
