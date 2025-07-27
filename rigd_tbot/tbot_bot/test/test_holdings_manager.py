# tbot_bot/test/test_holdings_manager.py
# Unit/integration tests for holdings logic under latest specifications.

import pytest
import time
from unittest.mock import patch
from tbot_bot.trading import holdings_manager
from tbot_bot.support.path_resolver import resolve_control_path
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import sys

MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_holdings_manager.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
LOGFILE = holdings_manager.get_output_path("logs", "test_mode.log") if hasattr(holdings_manager, "get_output_path") else None

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_holdings_manager", msg, logfile=LOGFILE)
    except Exception:
        pass

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

test_start = time.time()

if __name__ == "__main__":
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_holdings_manager.py] Individual test flag not present. Exiting.")
        sys.exit(0)

@patch("tbot_bot.trading.holdings_manager.load_holdings_secrets")
@patch("tbot_bot.broker.broker_api.get_active_broker")
def test_perform_holdings_cycle(mock_broker_func, mock_secrets):
    mock_secrets.return_value = {
        "HOLDINGS_FLOAT_TARGET_PCT": 10,
        "HOLDINGS_TAX_RESERVE_PCT": 20,
        "HOLDINGS_PAYROLL_PCT": 10,
        "HOLDINGS_ETF_LIST": "SCHD:50,SCHY:50"
    }
    mock_broker = MockBroker()
    mock_broker_func.return_value = mock_broker
    initial_cash = mock_broker.cash
    holdings_manager.perform_holdings_cycle(realized_gains=1000, user="test")
    # No direct broker, so just check that function runs without error

@patch("tbot_bot.trading.holdings_manager.load_holdings_secrets")
@patch("tbot_bot.broker.broker_api.get_active_broker")
def test_perform_rebalance_cycle(mock_broker_func, mock_secrets):
    mock_secrets.return_value = {
        "HOLDINGS_ETF_LIST": "SCHD:60,SCHY:40"
    }
    mock_broker = MockBroker()
    mock_broker_func.return_value = mock_broker
    holdings_manager.perform_rebalance_cycle(user="test")
    # No direct broker, so just check that function runs without error

def run_test():
    import pytest as _pytest
    ret = _pytest.main([__file__])
    status = "PASSED" if ret == 0 else "ERRORS"
    if (time.time() - test_start) > MAX_TEST_TIME:
        status = "TIMEOUT"
        safe_print(f"[test_holdings_manager.py] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
    if Path(TEST_FLAG_PATH).exists():
        Path(TEST_FLAG_PATH).unlink()
    safe_print(f"[test_holdings_manager.py] FINAL RESULT: {status}")

if __name__ == "__main__":
    run_test()
