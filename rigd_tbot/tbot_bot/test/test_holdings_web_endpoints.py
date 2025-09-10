# tbot_bot/test/test_holdings_web_endpoints.py
# Tests for new Flask blueprint.

import pytest
import time
from flask import Flask
from tbot_web.py.holdings_web import holdings_web
from tbot_bot.support.path_resolver import resolve_control_path
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import sys
from datetime import datetime, timezone
print(f"[LAUNCH] test_holdings_web_endpoints launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)


MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_holdings_web_endpoints.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"

@pytest.fixture
def test_client():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(holdings_web, url_prefix="/holdings")
    return app.test_client()

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_holdings_web_endpoints", msg)
    except Exception:
        pass

test_start = time.time()

if __name__ == "__main__":
    result = "PASSED"
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_holdings_web_endpoints.py] Individual test flag not present. Exiting.")
        sys.exit(0)
    try:
        import pytest as _pytest
        ret = _pytest.main([__file__])
        if ret != 0:
            result = "ERRORS"
        if (time.time() - test_start) > MAX_TEST_TIME:
            result = "TIMEOUT"
            safe_print(f"[test_holdings_web_endpoints.py] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
    except Exception as e:
        result = "ERRORS"
        safe_print(f"[test_holdings_web_endpoints.py] Exception: {e}")
    finally:
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()
        safe_print(f"[test_holdings_web_endpoints.py] FINAL RESULT: {result}")

def test_get_holdings_config(test_client):
    resp = test_client.get("/holdings/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "HOLDINGS_ETF_LIST" in data
    assert isinstance(data["HOLDINGS_ETF_LIST"], str)

def test_post_holdings_config_valid(test_client):
    payload = {
        "HOLDINGS_FLOAT_TARGET_PCT": 10,
        "HOLDINGS_TAX_RESERVE_PCT": 20,
        "HOLDINGS_PAYROLL_PCT": 10,
        "HOLDINGS_REBALANCE_INTERVAL": 6,
        "HOLDINGS_ETF_LIST": "SCHD:50,SCHY:50"
    }
    resp = test_client.post("/holdings/config", json=payload)
    assert resp.status_code == 200

def test_get_holdings_status(test_client):
    resp = test_client.get("/holdings/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "account_value" in data
    assert "cash" in data
    assert "etf_holdings" in data
    assert "next_rebalance_due" in data
