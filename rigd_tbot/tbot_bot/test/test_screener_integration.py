# tbot_bot/test/test_screener_integration.py
# Integration tests for screener modules using universe cache

import unittest
from tbot_bot.screeners.alpaca_screener import AlpacaScreener
from tbot_bot.screeners.finnhub_screener import FinnhubScreener
from tbot_bot.screeners.ibkr_screener import IBKRScreener

class TestScreenerIntegration(unittest.TestCase):
    def test_alpaca_screener(self):
        screener = AlpacaScreener()
        candidates = screener.run_screen()
        self.assertIsInstance(candidates, list)

    def test_finnhub_screener(self):
        screener = FinnhubScreener()
        candidates = screener.run_screen()
        self.assertIsInstance(candidates, list)

    def test_ibkr_screener(self):
        screener = IBKRScreener()
        candidates = screener.run_screen()
        self.assertIsInstance(candidates, list)

if __name__ == "__main__":
    unittest.main()
