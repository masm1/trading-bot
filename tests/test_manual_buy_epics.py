import unittest

from dashboard import manual_buy_order
from mapping import EPIC_MAP


class ManualBuyEpicMappingTests(unittest.TestCase):
    def test_confirmed_crypto_epics_are_available(self):
        self.assertEqual(EPIC_MAP["BTC"], "CS.D.BITCOIN.CFD.IP")
        self.assertEqual(EPIC_MAP["ETH"], "CS.D.ETHUSD.CFD.IP")

    def test_manual_buy_order_repro(self):
        btc_result = manual_buy_order("BTC", 500)
        tsla_result = manual_buy_order("TSLA", 500)
        print("BTC_RESULT", btc_result)
        print("TSLA_RESULT", tsla_result)
        self.assertIsInstance(btc_result, dict)
        self.assertIsInstance(tsla_result, dict)


if __name__ == "__main__":
    unittest.main()
