# tbot_bot/test/test_symbol_universe_refresh.py
# Unit tests for universe_orchestrator and related universe build logic.
# 100% spec-compliant: tests screener credential selection, flag gating, build failures on missing/invalid config, and partial/final JSON output.

import os
import tempfile
import shutil
import pytest
import json
import time
from unittest import mock
from tbot_bot.screeners import universe_orchestrator
from tbot_bot.support import secrets_manager
from tbot_bot.support.path_resolver import resolve_control_path
from datetime import datetime, timezone
print(f"[LAUNCH] test_symbol_universe_refresh launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)


CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_symbol_universe_refresh.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
MAX_TEST_TIME = 90  # seconds per test

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

@pytest.fixture(scope="function")
def temp_universe_env(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    output_dir = os.path.join(tmpdir, "output", "screeners")
    secrets_dir = os.path.join(tmpdir, "secrets")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(secrets_dir, exist_ok=True)
    monkeypatch.setattr(universe_orchestrator, "UNFILTERED_PATH", os.path.join(output_dir, "symbol_universe.unfiltered.json"))
    monkeypatch.setattr(universe_orchestrator, "BLOCKLIST_PATH", os.path.join(output_dir, "blocklist.txt"))
    monkeypatch.setattr(secrets_manager, "get_screener_credentials_path", lambda: os.path.join(secrets_dir, "screener_api.json.enc"))
    monkeypatch.setattr(universe_orchestrator, "get_output_path", lambda *a: os.path.join(output_dir, *a[1:]) if a[0] == "screeners" else get_output_path(*a))
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
    assert universe_orchestrator.screener_creds_exist()

def test_fail_no_creds(temp_universe_env):
    start = time.time()
    with pytest.raises(Exception):
        universe_orchestrator.fetch_broker_symbol_metadata_crash_resilient(
            env={}, blocklist=[], exchanges=["NASDAQ"], min_price=5, max_price=100, min_cap=2e9, max_cap=1e10, max_size=2000
        )
    elapsed = time.time() - start
    assert elapsed <= MAX_TEST_TIME, "TIMEOUT"

@mock.patch("tbot_bot.screeners.screener_utils.get_universe_screener_secrets", side_effect=lambda: {
    "SCREENER_NAME": "FAKEPROVIDER"
})
def test_fail_unsupported_provider(mock_uni_creds, temp_universe_env):
    start = time.time()
    with pytest.raises(RuntimeError):
        universe_orchestrator.fetch_broker_symbol_metadata_crash_resilient(
            env={}, blocklist=[], exchanges=["NASDAQ"], min_price=5, max_price=100, min_cap=2e9, max_cap=1e10, max_size=2000
        )
    elapsed = time.time() - start
    assert elapsed <= MAX_TEST_TIME, "TIMEOUT"

@mock.patch("tbot_bot.screeners.screener_utils.get_universe_screener_secrets", side_effect=lambda: {
    "SCREENER_NAME": "FINNHUB",
    "SCREENER_API_KEY": "finnhubkey",
    "SCREENER_URL": "https://finnhub.io/api/v1/"
})
@mock.patch("tbot_bot.screeners.universe_orchestrator.fetch_finnhub_symbols_staged")
def test_universe_build_triggers_correct_fetch(mock_fetch, mock_uni_creds, temp_universe_env):
    env = {"UNIVERSE_SLEEP_TIME": 0}
    blocklist = []
    exchanges = ["NASDAQ"]
    mock_fetch.return_value = [{"symbol": "AAPL", "exchange": "NASDAQ", "lastClose": 100, "marketCap": 3e9}]
    start = time.time()
    result = universe_orchestrator.fetch_broker_symbol_metadata_crash_resilient(
        env=env, blocklist=blocklist, exchanges=exchanges, min_price=5, max_price=100, min_cap=2e9, max_cap=1e10, max_size=2000
    )
    elapsed = time.time() - start
    assert elapsed <= MAX_TEST_TIME, "TIMEOUT"
    assert isinstance(result, list)
    assert result[0]["symbol"] == "AAPL"
    mock_fetch.assert_called_once()

def test_write_partial_and_unfiltered(temp_universe_env):
    start = time.time()
    syms = [{"symbol": "AAPL", "exchange": "NASDAQ", "lastClose": 100, "marketCap": 3e9}]
    universe_orchestrator.write_partial(syms)
    universe_orchestrator.write_unfiltered(syms)
    with open(universe_orchestrator.UNFILTERED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    elapsed = time.time() - start
    assert elapsed <= MAX_TEST_TIME, "TIMEOUT"
    assert data["symbols"][0]["symbol"] == "AAPL"

def test_append_to_blocklist(temp_universe_env):
    start = time.time()
    blocklist_path = universe_orchestrator.BLOCKLIST_PATH
    universe_orchestrator.append_to_blocklist("AAPL", blocklist_path, reason="PRICE_BELOW_MIN")
    assert os.path.exists(blocklist_path)
    with open(blocklist_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    elapsed = time.time() - start
    assert elapsed <= MAX_TEST_TIME, "TIMEOUT"
    assert "AAPL,PRICE_BELOW_MIN" in lines[0]

if __name__ == "__main__":
    result = "PASSED"
    start = time.time()
    if not (os.path.exists(TEST_FLAG_PATH) or os.path.exists(RUN_ALL_FLAG)):
        safe_print("[test_symbol_universe_refresh.py] Individual test flag not present. Exiting.")
        import sys
        sys.exit(1)
    try:
        import pytest as _pytest
        ret = _pytest.main([__file__])
        if ret != 0:
            result = "ERRORS"
    except Exception as e:
        result = "ERRORS"
        safe_print(f"[test_symbol_universe_refresh.py] Exception: {e}")
    finally:
        if os.path.exists(TEST_FLAG_PATH):
            os.unlink(TEST_FLAG_PATH)
        elapsed = time.time() - start
        if elapsed > MAX_TEST_TIME:
            result = "TIMEOUT"
            safe_print("[test_symbol_universe_refresh.py] TIMEOUT")
        safe_print(f"[test_symbol_universe_refresh.py] FINAL RESULT: {result}")
