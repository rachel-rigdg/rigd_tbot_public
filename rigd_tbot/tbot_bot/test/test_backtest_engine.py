# tbot_bot/test/test_backtest_engine.py
# Regression test for backtest engine accuracy (isolated to test context)

import pytest
from tbot_bot.backtest.backtest_engine import run_backtest
from tbot_bot.config.env_bot import get_bot_config

@pytest.fixture
def backtest_config(monkeypatch):
    # Patch STRATEGY_SEQUENCE directly for isolated simulation
    monkeypatch.setenv("STRATEGY_SEQUENCE", "open,mid,close")
    return get_bot_config()

def test_backtest_open(backtest_config):
    result = run_backtest(
        strategy="open",
        start_date="2023-01-01",
        end_date="2023-01-31",
        data_source="tbot_bot/backtest/data/open_ohlcv_sample.csv"
    )
    assert isinstance(result, list)
    assert all("entry_price" in trade for trade in result)
    assert all("symbol" in trade for trade in result)

def test_backtest_mid(backtest_config):
    result = run_backtest(
        strategy="mid",
        start_date="2023-01-01",
        end_date="2023-01-31",
        data_source="tbot_bot/backtest/data/mid_ohlcv_sample.csv"
    )
    assert isinstance(result, list)
    assert all("PnL" in trade for trade in result)

def test_backtest_close(backtest_config):
    result = run_backtest(
        strategy="close",
        start_date="2023-01-01",
        end_date="2023-01-31",
        data_source="tbot_bot/backtest/data/close_ohlcv_sample.csv"
    )
    assert isinstance(result, list)
    assert any(trade["side"] in ["long", "short"] for trade in result)

def test_invalid_strategy(backtest_config):
    with pytest.raises(Exception):
        run_backtest(
            strategy="invalid",
            start_date="2023-01-01",
            end_date="2023-01-31",
            data_source="tbot_bot/backtest/data/invalid.csv"
        )
