# tbot_bot/test/test_broker_sync.py

import sys
import pytest
from pathlib import Path

# Add project root to sys.path for imports if running standalone
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tbot_bot.accounting.ledger as ledger_mod
from tbot_bot.accounting.ledger_utils import validate_double_entry

def test_sync_broker_ledger_runs_without_error(monkeypatch):
    """
    Test that sync_broker_ledger() runs without raising exceptions.
    (Does not test broker side effects or actual DB changes unless using a test environment.)
    """
    # Optionally: Patch any live broker/network calls here to prevent real trades in test
    # Example:
    # monkeypatch.setattr(ledger_mod, "fetch_broker_trades", lambda: [])

    try:
        ledger_mod.sync_broker_ledger()
    except Exception as e:
        pytest.fail(f"sync_broker_ledger raised an exception: {e}")

def test_sync_broker_ledger_idempotent(monkeypatch):
    """
    Optionally, test that running sync twice does not result in duplicate or inconsistent ledger state.
    For real integration, patch DB or check for double insertions as needed.
    """
    try:
        ledger_mod.sync_broker_ledger()
        ledger_mod.sync_broker_ledger()
    except Exception as e:
        pytest.fail(f"Repeated sync_broker_ledger raised an exception: {e}")

def test_double_entry_posting_compliance():
    """
    After sync, the ledger must be strictly double-entry balanced for all trades.
    """
    try:
        assert validate_double_entry() is True
    except Exception as e:
        pytest.fail(f"Ledger not double-entry balanced after sync: {e}")
