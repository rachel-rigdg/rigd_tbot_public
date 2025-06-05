# tbot_bot/accounting/accounting_config.py 
# Validates and creates required output folder structure; enforces ledger/COA existence and schema compliance

import os
import json
from cryptography.fernet import Fernet
from pathlib import Path
from tbot_bot.support.path_resolver import resolve_output_folder_path, resolve_ledger_db_path, resolve_coa_db_path

def ensure_output_folder_structure():
    """
    Validates and creates all required output folders for logs, ledgers, summaries, and trades.
    """
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    BOT_IDENTITY = bot_identity_data.get("BOT_IDENTITY_STRING")
    OUTPUT_FOLDER = resolve_output_folder_path(BOT_IDENTITY)
    subdirs = ["logs", "ledgers", "summaries", "trades"]
    for sub in subdirs:
        subdir_path = os.path.join(OUTPUT_FOLDER, sub)
        os.makedirs(subdir_path, exist_ok=True)
    print(f"[accounting_config] Output folders ensured for {BOT_IDENTITY}")

def get_bot_identity_data():
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    return json.loads(plaintext.decode("utf-8"))

def get_ledger_paths():
    bot_identity_data = get_bot_identity_data()
    BOT_IDENTITY = bot_identity_data.get("BOT_IDENTITY_STRING")
    OUTPUT_FOLDER = resolve_output_folder_path(BOT_IDENTITY)
    LEDGER_PATH = resolve_ledger_db_path(*BOT_IDENTITY.split("_"))
    FLOAT_LEDGER_PATH = os.path.join(OUTPUT_FOLDER, "ledgers", f"{BOT_IDENTITY}_BOT_FLOAT_ledger.db")
    COA_LEDGER_PATH = resolve_coa_db_path(*BOT_IDENTITY.split("_"))
    return LEDGER_PATH, FLOAT_LEDGER_PATH, COA_LEDGER_PATH
