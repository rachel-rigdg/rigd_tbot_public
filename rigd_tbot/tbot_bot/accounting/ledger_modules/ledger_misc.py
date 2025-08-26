# tbot_bot/accounting/ledger_modules/ledger_misc.py

import sqlite3
import json
from cryptography.fernet import Fernet
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import compliance_filter_ledger_entry

def get_coa_accounts():
    CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
    TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"
    if TEST_MODE_FLAG.exists():
        return []
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    identity = bot_identity_data.get("BOT_IDENTITY_STRING")
    entity_code, jurisdiction_code, broker_code, bot_id = identity.split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT json_extract(account_json, '$.code'), json_extract(account_json, '$.name') FROM coa_accounts")
        accounts = sorted([(row[0], row[1]) for row in cursor.fetchall() if row[0] and row[1]], key=lambda x: x[1])
    # Compliance filter not directly relevant here, but if ever returning ledger entries, filter via compliance_filter_ledger_entry
    return accounts
