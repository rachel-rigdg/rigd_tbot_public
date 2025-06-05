# tbot_bot/accounting/accounting_api.py
# Exports finalized trade/report data to accounting system endpoint (post-trade only, no live config)

import json
from cryptography.fernet import Fernet
from pathlib import Path

from tbot_bot.config.env_bot import env_config
from tbot_bot.config.error_handler import handle_error
from tbot_bot.accounting.tradebot_exporter import TradeBotExporter
from tbot_bot.support.path_resolver import resolve_ledger_db_path

# Load configuration from .env_bot
EXPORT_MODE = env_config.get("LEDGER_EXPORT_MODE", "auto").lower()  # Options: auto, off

# Decrypt BOT_IDENTITY_STRING from secret
try:
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    BOT_IDENTITY = bot_identity_data.get("BOT_IDENTITY_STRING")
    ENTITY, JURISDICTION, BROKER, BOT_ID = BOT_IDENTITY.split("_")
except Exception as e:
    BOT_IDENTITY = None
    ENTITY = JURISDICTION = BROKER = BOT_ID = None

def export_transactions(transactions, session_tag=""):
    """
    Dispatches a list of validated trade transactions to the accounting backend.
    Args:
        transactions (list): List of AccountTransaction objects.
        session_tag (str): Optional tag for audit or session identification.
    """
    if EXPORT_MODE != "auto" or not BOT_IDENTITY:
        return  # Skip export if disabled or identity missing

    try:
        ledger_path = resolve_ledger_db_path(ENTITY, JURISDICTION, BROKER, BOT_ID)
        exporter = TradeBotExporter(ledger_path=ledger_path, session_tag=session_tag)
        exporter.write_transactions(transactions)
    except Exception as e:
        handle_error(
            module="accounting_api",
            error_type="ExportError",
            error_msg="Failed to export transactions",
            exception=e
        )
