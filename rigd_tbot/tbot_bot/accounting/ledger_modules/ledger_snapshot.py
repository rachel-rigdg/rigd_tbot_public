# tbot_bot/accounting/ledger_modules/ledger_snapshot.py

import os
from datetime import datetime
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_ledger_db_path, resolve_ledger_snapshot_dir
from tbot_bot.support.decrypt_secrets import load_bot_identity

def snapshot_ledger_before_sync():
    """
    Atomically snapshot the current ledger DB before sync/critical operation.
    """
    identity = load_bot_identity()
    entity_code, jurisdiction_code, broker_code, bot_id = identity.split("_")
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    snapshot_dir = resolve_ledger_snapshot_dir(entity_code, jurisdiction_code, broker_code, bot_id)
    os.makedirs(snapshot_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    snapshot_name = f"ledger_snapshot_{timestamp}.db"
    snapshot_path = os.path.join(snapshot_dir, snapshot_name)
    with open(db_path, "rb") as src, open(snapshot_path, "wb") as dst:
        dst.write(src.read())
    return snapshot_path
