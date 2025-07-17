# tbot_bot/test/test_backtest_engine.py
# Regression test for backtest engine accuracy (isolated to test context)
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import sys
from pathlib import Path

TEST_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode_backtest_engine.flag"
RUN_ALL_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

if __name__ == "__main__":
    if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
        safe_print("[test_backtest_engine.py] Individual test flag not present. Exiting.")
        sys.exit(0)

import pytest
from tbot_bot.backtest.backtest_engine import run_backtest
from tbot_bot.config.env_bot import get_bot_config

@pytest.fixture
def backtest_config(monkeypatch):
    monkeypatch.setenv("STRATEGY_SEQUENCE", "open,mid,close")
    return get_bot_config()

def test_backtest_open(backtest_config):
    safe_print("Running test_backtest_open...")
    result = run_backtest(
        strategy="open",
        start_date="2023-01-01",
        end_date="2023-01-31",
        data_source="tbot_bot/backtest/data/open_ohlcv_sample.csv"
    )
    assert isinstance(result, list)
    assert all("entry_price" in trade for trade in result)
    assert all("symbol" in trade for trade in result)
    safe_print("test_backtest_open PASSED")

def test_backtest_mid(backtest_config):
    safe_print("Running test_backtest_mid...")
    result = run_backtest(
        strategy="mid",
        start_date="2023-01-01",
        end_date="2023-01-31",
        data_source="tbot_bot/backtest/data/mid_ohlcv_sample.csv"
    )
    assert isinstance(result, list)
    assert all("PnL" in trade for trade in result)
    safe_print("test_backtest_mid PASSED")

def test_backtest_close(backtest_config):
    safe_print("Running test_backtest_close...")
    result = run_backtest(
        strategy="close",
        start_date="2023-01-01",
        end_date="2023-01-31",
        data_source="tbot_bot/backtest/data/close_ohlcv_sample.csv"
    )
    assert isinstance(result, list)
    assert any(trade["side"] in ["long", "short"] for trade in result)
    safe_print("test_backtest_close PASSED")

def test_invalid_strategy(backtest_config):
    safe_print("Running test_invalid_strategy...")
    try:
        run_backtest(
            strategy="invalid",
            start_date="2023-01-01",
            end_date="2023-01-31",
            data_source="tbot_bot/backtest/data/invalid.csv"
        )
    except Exception:
        safe_print("test_invalid_strategy PASSED")
        return
    assert False, "test_invalid_strategy FAILED (no exception raised)"

def run_test():
    import pytest as _pytest
    ret = _pytest.main([__file__])
    if TEST_FLAG_PATH.exists():
        TEST_FLAG_PATH.unlink()
    if ret == 0:
        safe_print("[test_backtest_engine.py] ALL TESTS PASSED")
    else:
        safe_print(f"[test_backtest_engine.py] ONE OR MORE TESTS FAILED (code={ret})")

if __name__ == "__main__":
    run_test()
