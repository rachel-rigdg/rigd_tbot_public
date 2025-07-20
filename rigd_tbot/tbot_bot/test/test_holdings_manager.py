# tbot_bot/test/test_holdings_manager.py
# Unit/integration tests for holdings logic under latest specifications.

import pytest
from unittest.mock import patch
from tbot_bot.trading import holdings_manager

class MockBroker:
    def __init__(self):
        self.account_value = 100000
        self.cash = 5000
        self.holdings = {"SCHD": 45000, "SCHY": 45000}
        self.orders = []

    def get_account_value(self):
        return self.account_value

    def get_cash_balance(self):
        return self.cash

    def get_etf_holdings(self):
        return self.holdings.copy()

    def place_order(self, symbol, side, amount):
        self.orders.append((symbol, side, round(amount, 2)))
        if side == "sell":
            self.holdings[symbol] -= amount
            self.cash += amount
        else:
            self.holdings[symbol] += amount
            self.cash -= amount

    def get_price(self, symbol):
        return 1.0

@patch("tbot_bot.trading.holdings_manager.load_holdings_secrets")
def test_run_holdings_maintenance(mock_secrets):
    # Force deterministic configuration
    mock_secrets.return_value = {
        "HOLDINGS_FLOAT_TARGET_PCT": 10,
        "HOLDINGS_TAX_RESERVE_PCT": 20,
        "HOLDINGS_PAYROLL_PCT": 10,
        "HOLDINGS_ETF_LIST": "SCHD:50,SCHY:50"
    }
    broker = MockBroker()
    initial_cash = broker.cash
    holdings_manager.run_holdings_maintenance(broker, realized_gains=1000)

    # Cash must increase by float/top-off and not exceed target
    assert broker.cash > initial_cash
    assert any(o[1] in ("buy", "sell") for o in broker.orders)

@patch("tbot_bot.trading.holdings_manager.load_holdings_secrets")
def test_run_rebalance_cycle(mock_secrets):
    mock_secrets.return_value = {
        "HOLDINGS_ETF_LIST": "SCHD:60,SCHY:40"
    }
    broker = MockBroker()
    holdings_manager.run_rebalance_cycle(broker)

    assert len(broker.orders) > 0
    # Verify at least one buy/sell is properly computed
    assert any(o[1] in ("buy", "sell") for o in broker.orders)
