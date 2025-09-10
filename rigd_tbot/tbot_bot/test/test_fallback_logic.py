# test/test_fallback_logic.py

import pytest
from unittest.mock import MagicMock, patch
import time
import threading
from datetime import datetime, timezone
print(f"[LAUNCH] test_fallback_logic launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)


MAX_TEST_TIME = 90  # seconds per test

# Patch all config/env/secret loads to return fixed, deterministic configs for testing.
MOCK_CONFIG = {
    "MAX_TRADES": 2,
    "CANDIDATE_MULTIPLIER": 3,
    "FRACTIONAL": True,
    "WEIGHTS": "0.5,0.5",
    "ACCOUNT_BALANCE": 10000.0,
    "MAX_RISK_PER_TRADE": 0.05,
    "STRAT_OPEN_ENABLED": True,
    "STRAT_OPEN_BUFFER": 0.01,
    "OPEN_ANALYSIS_TIME": 1,
    "OPEN_BREAKOUT_TIME": 1,
    "OPEN_MONITORING_TIME": 1,
    "SHORT_TYPE_OPEN": "disabled"
}

@pytest.fixture(autouse=True)
def patch_bot_config(monkeypatch):
    monkeypatch.setattr("tbot_bot.config.env_bot.get_bot_config", lambda: MOCK_CONFIG)

def mock_broker_api_supports_fractional(symbol):
    # Only even symbols are fractional
    return int(symbol[-1]) % 2 == 0

def mock_broker_api_get_min_order_size(symbol):
    # Odd symbols require more capital than default allocation
    return 6000 if int(symbol[-1]) % 2 == 1 else 100

def make_candidate(symbol):
    return {"symbol": symbol, "price": 100.0, "vwap": 100.0}

def run_with_timeout(func, timeout=MAX_TEST_TIME):
    """Runs a function with a timeout. Raises AssertionError if times out."""
    result = {}
    def wrapper():
        try:
            result['ret'] = func()
        except Exception as e:
            result['exc'] = e

    t = threading.Thread(target=wrapper)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise AssertionError(f"TIMEOUT: test did not complete in {timeout} seconds")
    if 'exc' in result:
        raise result['exc']
    return result.get('ret', None)

def test_candidate_ranking_and_rejection(monkeypatch):
    def inner():
        import tbot_bot.strategy.strategy_open as strat_open

        # Patch broker_api
        monkeypatch.setattr(strat_open, "get_broker_api", lambda: MagicMock(
            supports_fractional=mock_broker_api_supports_fractional,
            get_min_order_size=mock_broker_api_get_min_order_size
        ))

        # Prepare candidates: some ineligible for fractional/min order size
        candidates = [make_candidate(f"TICKER{i}") for i in range(1, 7)]
        mock_screener = MagicMock()
        mock_screener.run_screen.return_value = candidates

        # Patch is_test_mode_active to True
        monkeypatch.setattr(strat_open, "is_test_mode_active", lambda: True)
        # Patch analyze_opening_range to fill range_data
        strat_open.range_data = {c["symbol"]: {"high": 102, "low": 98} for c in candidates}

        # Run detect_breakouts
        trades = strat_open.detect_breakouts(0, lambda strategy: mock_screener)
        # Only eligible candidates (even numbers, capital above min) should be attempted and returned
        eligible = [c["symbol"] for c in candidates if mock_broker_api_supports_fractional(c["symbol"]) and 500.0 >= mock_broker_api_get_min_order_size(c["symbol"])]
        assert all(any(t["ticker"] == s for t in trades) for s in eligible)
        # Check SESSION_LOGS populated
        assert hasattr(strat_open, "SESSION_LOGS")
        assert any(e["status"] == "rejected" for e in strat_open.SESSION_LOGS)
    run_with_timeout(inner)

def test_fallback_pool_does_not_duplicate_logic(monkeypatch):
    def inner():
        import tbot_bot.strategy.strategy_open as strat_open

        # Patch broker_api with only non-fractional
        monkeypatch.setattr(strat_open, "get_broker_api", lambda: MagicMock(
            supports_fractional=lambda s: False,
            get_min_order_size=lambda s: 100
        ))

        candidates = [make_candidate(f"TICKER{i}") for i in range(1, 4)]
        mock_screener = MagicMock()
        mock_screener.run_screen.return_value = candidates

        monkeypatch.setattr(strat_open, "is_test_mode_active", lambda: True)
        strat_open.range_data = {c["symbol"]: {"high": 110, "low": 90} for c in candidates}

        trades = strat_open.detect_breakouts(0, lambda strategy: mock_screener)
        assert len(trades) == 0
        assert all(e["status"] == "rejected" for e in strat_open.SESSION_LOGS)
    run_with_timeout(inner)
