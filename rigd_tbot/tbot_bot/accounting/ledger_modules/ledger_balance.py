# tbot_bot/accounting/ledger_modules/ledger_balance.py

"""
Balance and running balance computation helpers for the ledger.
"""

from tbot_bot.accounting.ledger_modules.ledger_entry import load_internal_ledger
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from pathlib import Path
import sqlite3

CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def calculate_account_balances():
    """
    Computes the sum of total_value grouped by account from the trades table.
    Returns a dict of {account: balance}.
    """
    if TEST_MODE_FLAG.exists():
        return {}
    entity_code, jurisdiction_code, broker_code, bot_id = load_bot_identity().split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT account, SUM(total_value) as balance FROM trades GROUP BY account"
        )
        balances = {row[0]: row[1] for row in cursor.fetchall()}
    return balances

def calculate_running_balances():
    """
    Returns list of dicts: each ledger entry with added field 'running_balance'.
    """
    if TEST_MODE_FLAG.exists():
        return []
    entries = load_internal_ledger()
    # Sort by datetime_utc ascending, id as tiebreaker
    entries.sort(key=lambda e: (e.get("datetime_utc", ""), e.get("id", 0)))
    running = 0.0
    out = []
    for entry in entries:
        val = float(entry.get("total_value") or 0)
        running += val
        entry["running_balance"] = round(running, 2)
        out.append(entry)
    return out
