# tbot_bot/accounting/accounting_config.py 
# Validates and creates required output folder structure; enforces ledger/COA existence and schema compliance

import os
import json
from cryptography.fernet import Fernet
from pathlib import Path

# ⬇️ add get_bot_identity; keep existing resolvers
from tbot_bot.support.path_resolver import (
    get_bot_identity,
    resolve_output_folder_path,
    resolve_ledger_db_path,
    resolve_coa_db_path,
)

ROOT = Path(__file__).resolve().parents[2]
KEY_PATH = ROOT / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
ENC_PATH = ROOT / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"

def get_bot_identity_data():
    """
    Prefer canonical identity from path_resolver (single source of truth).
    Fallback to legacy Fernet decryption if needed.
    Returns a dict with BOT_IDENTITY_STRING for compatibility with callers.
    """
    try:
        bid = get_bot_identity()
        if bid:
            return {"BOT_IDENTITY_STRING": bid}
    except Exception:
        pass  # fall through to Fernet fallback

    # Legacy fallback (kept for compatibility in environments missing resolver wiring)
    key = KEY_PATH.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(ENC_PATH.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    return bot_identity_data

def ensure_output_folder_structure():
    """
    Validates and creates all required output folders for logs, ledgers, summaries, and trades.
    """
    bot_identity_data = get_bot_identity_data()
    BOT_IDENTITY = bot_identity_data.get("BOT_IDENTITY_STRING")
    if not BOT_IDENTITY:
        print("[accounting_config] BOT_IDENTITY_STRING missing, cannot create output folders")
        return
    output_folder = resolve_output_folder_path(BOT_IDENTITY)  # ✅ new signature
    for sub in ("logs", "ledgers", "summaries", "trades"):
        subdir_path = os.path.join(output_folder, sub)
        os.makedirs(subdir_path, exist_ok=True)
        print(f"[accounting_config] Ensured output subdir: {subdir_path}")

def get_ledger_paths():
    bot_identity_data = get_bot_identity_data()
    BOT_IDENTITY = bot_identity_data.get("BOT_IDENTITY_STRING")
    if not BOT_IDENTITY:
        return None, None
    try:
        ENTITY, JURISDICTION, BROKER, BOT_ID = BOT_IDENTITY.split("_", 3)
    except ValueError:
        print(f"[accounting_config] Unexpected BOT_IDENTITY format: {BOT_IDENTITY}")
        return None, None

    ledger_path = resolve_ledger_db_path(ENTITY, JURISDICTION, BROKER, BOT_ID)
    coa_path = resolve_coa_db_path(ENTITY, JURISDICTION, BROKER, BOT_ID)
    return ledger_path, coa_path
