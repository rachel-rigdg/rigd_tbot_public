# tbot_bot/accounting/ledger/ledger_balance.py

from .ledger_entry import get_all_ledger_entries
import sqlite3
import json
from cryptography.fernet import Fernet
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

BOT_ID = get_bot_identity()
CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def calculate_account_balances():
    if TEST_MODE_FLAG.exists():
        return {}
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "acct_api.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity_data.get("BOT_IDENTITY_STRING").split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT account, SUM(total_value) as balance FROM trades GROUP BY account"
        )
        balances = {row[0]: row[1] for row in cursor.fetchall()}
    return balances

def calculate_running_balances():
    if TEST_MODE_FLAG.exists():
        return []
    entries = get_all_ledger_entries()
    entries.sort(key=lambda e: (e.get("datetime_utc", ""), e.get("id", 0)))
    running = 0.0
    out = []
    for entry in entries:
        val = float(entry.get("total_value") or 0)
        running += val
        entry["running_balance"] = round(running, 2)
        out.append(entry)
    return out
