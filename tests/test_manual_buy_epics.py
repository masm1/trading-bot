import unittest

from mapping import EPIC_MAP


class ManualBuyEpicMappingTests(unittest.TestCase):
    def test_confirmed_crypto_epics_are_available(self):
        self.assertEqual(EPIC_MAP["BTC"], "CS.D.BITCOIN.CFD.IP")
        self.assertEqual(EPIC_MAP["ETH"], "CS.D.ETHUSD.CFD.IP")


if __name__ == "__main__":
    unittest.main()
