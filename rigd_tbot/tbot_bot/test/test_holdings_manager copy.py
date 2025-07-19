# tbot_bot/test/test_holdings_manager.py
# Unit/integration tests for holdings logic.

import pytest
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

def test_run_holdings_maintenance():
    broker = MockBroker()
    holdings_manager.run_holdings_maintenance(broker, realized_gains=1000)
    assert broker.cash > 5000  # Float topped up
    assert len(broker.orders) >= 1

def test_run_rebalance_cycle():
    broker = MockBroker()
    holdings_manager.run_rebalance_cycle(broker)
    assert len(broker.orders) >= 1
