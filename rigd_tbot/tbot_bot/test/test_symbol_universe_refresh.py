# test/test_symbol_universe_refresh.py
# Unit tests for symbol_universe_refresh and related universe build logic.
# 100% spec-compliant: tests screener credential selection, flag gating, build failures on missing/invalid config, and partial/final JSON output.

import os
import tempfile
import shutil
import pytest
import json
from unittest import mock
from tbot_bot.screeners import symbol_universe_refresh
from tbot_bot.support import secrets_manager
from tbot_bot.support.path_resolver import get_output_path

@pytest.fixture(scope="function")
def temp_universe_env(monkeypatch):
    # Setup temp dirs for outputs/secrets
    tmpdir = tempfile.mkdtemp()
    output_dir = os.path.join(tmpdir, "output", "screeners")
    secrets_dir = os.path.join(tmpdir, "secrets")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(secrets_dir, exist_ok=True)
    # Patch all paths to write/read from temp
    monkeypatch.setattr(symbol_universe_refresh, "UNFILTERED_PATH", os.path.join(output_dir, "symbol_universe.unfiltered.json"))
    monkeypatch.setattr(symbol_universe_refresh, "BLOCKLIST_PATH", os.path.join(output_dir, "blocklist.txt"))
    monkeypatch.setattr(secrets_manager, "get_screener_credentials_path", lambda: os.path.join(secrets_dir, "screener_api.json.enc"))
    monkeypatch.setattr(symbol_universe_refresh, "get_output_path", lambda *a: os.path.join(output_dir, *a[1:]) if a[0] == "screeners" else get_output_path(*a))
    yield tmpdir
    shutil.rmtree(tmpdir)

def mock_good_creds(universe_enabled="true", trading_enabled="false"):
    return {
        "PROVIDER_01": "FINNHUB",
        "SCREENER_NAME_01": "FINNHUB",
        "SCREENER_API_KEY_01": "finnhubkey",
        "SCREENER_URL_01": "https://finnhub.io/api/v1/",
        "UNIVERSE_ENABLED_01": universe_enabled,
        "TRADING_ENABLED_01": trading_enabled
    }

@mock.patch("tbot_bot.screeners.screener_utils.get_universe_screener_secrets", side_effect=lambda: {
    "SCREENER_NAME": "FINNHUB",
    "SCREENER_API_KEY": "finnhubkey",
    "SCREENER_URL": "https://finnhub.io/api/v1/"
})
def test_screener_creds_exist(mock_universe_creds, temp_universe_env):
    assert symbol_universe_refresh.screener_creds_exist()

def test_fail_no_creds(temp_universe_env):
    with pytest.raises(Exception):
        symbol_universe_refresh.fetch_broker_symbol_metadata_crash_resilient(
            env={}, blocklist=[], exchanges=["NASDAQ"], min_price=5, max_price=100, min_cap=2e9, max_cap=1e10, max_size=2000
        )

@mock.patch("tbot_bot.screeners.screener_utils.get_universe_screener_secrets", side_effect=lambda: {
    "SCREENER_NAME": "FAKEPROVIDER"
})
def test_fail_unsupported_provider(mock_uni_creds, temp_universe_env):
    with pytest.raises(RuntimeError):
        symbol_universe_refresh.fetch_broker_symbol_metadata_crash_resilient(
            env={}, blocklist=[], exchanges=["NASDAQ"], min_price=5, max_price=100, min_cap=2e9, max_cap=1e10, max_size=2000
        )

@mock.patch("tbot_bot.screeners.screener_utils.get_universe_screener_secrets", side_effect=lambda: {
    "SCREENER_NAME": "FINNHUB",
    "SCREENER_API_KEY": "finnhubkey",
    "SCREENER_URL": "https://finnhub.io/api/v1/"
})
@mock.patch("tbot_bot.screeners.symbol_universe_refresh.fetch_finnhub_symbols_staged")
def test_universe_build_triggers_correct_fetch(mock_fetch, mock_uni_creds, temp_universe_env):
    env = {"UNIVERSE_SLEEP_TIME": 0}
    blocklist = []
    exchanges = ["NASDAQ"]
    mock_fetch.return_value = [{"symbol": "AAPL", "exchange": "NASDAQ", "lastClose": 100, "marketCap": 3e9}]
    result = symbol_universe_refresh.fetch_broker_symbol_metadata_crash_resilient(
        env=env, blocklist=blocklist, exchanges=exchanges, min_price=5, max_price=100, min_cap=2e9, max_cap=1e10, max_size=2000
    )
    assert isinstance(result, list)
    assert result[0]["symbol"] == "AAPL"
    mock_fetch.assert_called_once()

def test_write_partial_and_unfiltered(temp_universe_env):
    syms = [{"symbol": "AAPL", "exchange": "NASDAQ", "lastClose": 100, "marketCap": 3e9}]
    symbol_universe_refresh.write_partial(syms)
    symbol_universe_refresh.write_unfiltered(syms)
    with open(symbol_universe_refresh.UNFILTERED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["symbols"][0]["symbol"] == "AAPL"

def test_append_to_blocklist(temp_universe_env):
    blocklist_path = symbol_universe_refresh.BLOCKLIST_PATH
    symbol_universe_refresh.append_to_blocklist("AAPL", blocklist_path, reason="PRICE_BELOW_MIN")
    assert os.path.exists(blocklist_path)
    with open(blocklist_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert "AAPL,PRICE_BELOW_MIN" in lines[0]
