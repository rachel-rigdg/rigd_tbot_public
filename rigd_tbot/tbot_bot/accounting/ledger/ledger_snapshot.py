# tbot_bot/accounting/ledger/ledger_snapshot.py

import os
from datetime import datetime
from cryptography.fernet import Fernet
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_ledger_snapshot_dir
from tbot_bot.support.utils_identity import get_bot_identity

def snapshot_ledger_before_sync():
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity_data.get("BOT_IDENTITY_STRING").split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    snapshot_dir = resolve_ledger_snapshot_dir(entity_code, jurisdiction_code, broker_code, bot_id)
    os.makedirs(snapshot_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    snapshot_name = f"ledger_snapshot_{timestamp}.db"
    snapshot_path = os.path.join(snapshot_dir, snapshot_name)
    with open(db_path, "rb") as src, open(snapshot_path, "wb") as dst:
        dst.write(src.read())
    return snapshot_path
