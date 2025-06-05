# tbot_bot/accounting/init_coa_db.py
# Bootstrap script: initializes new COA DB at output/IDENTITY/ledgers/ using tbot_ledger_coa.json as hierarchy/template

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import os
import json
import sqlite3
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from tbot_bot.support.path_resolver import resolve_coa_db_path, resolve_coa_template_path

def utc_now():
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

def init_coa_db(entity_code=None, jurisdiction_code=None, broker_code=None, bot_id=None, coa_version="v1.0.0", currency_code="USD"):
    print(f"[init_coa_db] Starting COA DB initialization...")
    if not all([entity_code, jurisdiction_code, broker_code, bot_id]):
        key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
        enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
        print(f"[init_coa_db] Loading bot_identity from {enc_path}")
        key = key_path.read_bytes()
        cipher = Fernet(key)
        plaintext = cipher.decrypt(enc_path.read_bytes())
        bot_identity_data = json.loads(plaintext.decode("utf-8"))
        identity = bot_identity_data.get("BOT_IDENTITY_STRING")
        entity_code, jurisdiction_code, broker_code, bot_id = identity.split("_")
    coa_db_path = resolve_coa_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    coa_template_path = resolve_coa_template_path()
    print(f"[init_coa_db] COA DB path: {coa_db_path}")
    print(f"[init_coa_db] COA template path: {coa_template_path}")
    os.makedirs(os.path.dirname(coa_db_path), exist_ok=True)
    if os.path.exists(coa_db_path):
        print(f"[init_coa_db] Removing existing COA DB: {coa_db_path}")
        os.remove(coa_db_path)
    try:
        with open(coa_template_path, "r", encoding="utf-8") as template_file:
            coa_accounts = json.load(template_file)
        print(f"[init_coa_db] Number of COA accounts in template: {len(coa_accounts)}")
        conn = sqlite3.connect(coa_db_path)
        conn.execute(
            "CREATE TABLE coa_metadata (currency_code TEXT NOT NULL, entity_code TEXT NOT NULL, jurisdiction_code TEXT NOT NULL, coa_version TEXT NOT NULL, created_at_utc TEXT NOT NULL, last_updated_utc TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE coa_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, account_json TEXT NOT NULL)"
        )
        now = utc_now()
        conn.execute(
            "INSERT INTO coa_metadata (currency_code, entity_code, jurisdiction_code, coa_version, created_at_utc, last_updated_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (currency_code, entity_code, jurisdiction_code, coa_version, now, now),
        )
        for acc in coa_accounts:
            conn.execute("INSERT INTO coa_accounts (account_json) VALUES (?)", (json.dumps(acc),))
        conn.commit()
        conn.close()
        print(f"[init_coa_db] COA DB created successfully at: {coa_db_path}")
    except Exception as e:
        print(f"[init_coa_db] ERROR: {e}")

if __name__ == "__main__":
    init_coa_db()
