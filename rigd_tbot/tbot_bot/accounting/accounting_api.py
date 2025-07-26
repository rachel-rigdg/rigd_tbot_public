# tbot_bot/accounting/accounting_api.py
# Exports finalized trade/report data to accounting system endpoint (post-trade only, no live config)

import json
from cryptography.fernet import Fernet
from pathlib import Path
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.config.error_handler_bot import handle_error
from tbot_bot.accounting.tradebot_exporter import TradeBotExporter
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.accounting.ledger.ledger_double_entry import validate_double_entry

# Load configuration from .env_bot
config = get_bot_config()
EXPORT_MODE = config.get("LEDGER_EXPORT_MODE", "auto").lower()  # Options: auto, off

# Decrypt BOT_IDENTITY_STRING from secret
try:
    key_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    BOT_IDENTITY = bot_identity_data.get("BOT_IDENTITY_STRING")
    ENTITY, JURISDICTION_CODE, BROKER, BOT_ID = BOT_IDENTITY.split("_")
except Exception as e:
    BOT_IDENTITY = None
    ENTITY = JURISDICTION_CODE = BROKER = BOT_ID = None

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
        ledger_path = resolve_ledger_db_path(ENTITY, JURISDICTION_CODE, BROKER, BOT_ID)
        # Enforce double-entry validation before any export
        validate_double_entry()
        exporter = TradeBotExporter(ledger_path=ledger_path, session_tag=session_tag)
        exporter.write_transactions(transactions)
    except Exception as e:
        handle_error(
            module="accounting_api",
            error_type="ExportError",
            error_msg="Failed to export transactions",
            exception=e
        )

def propose_external_transfer(transfer_type, amount, currency, notes=""):
    """
    Creates a transfer proposal for external float movement (tax, payroll, or operational).
    The proposal is written to output/{BOT_ID}/transfers/{transfer_type}_{timestamp}.json.
    Args:
        transfer_type (str): "tax_reserve", "payroll", "float_injection", etc.
        amount (float): Amount to transfer.
        currency (str): Currency code (e.g., "USD").
        notes (str): Optional details for audit.
    """
    if not BOT_ID:
        return

    from datetime import datetime
    proposal_dir = Path(__file__).resolve().parents[2] / "output" / BOT_ID / "transfers"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    proposal = {
        "bot_id": BOT_ID,
        "transfer_type": transfer_type,
        "amount": amount,
        "currency": currency,
        "notes": notes,
        "timestamp_utc": timestamp,
        "entity": ENTITY,
        "jurisdiction_code": JURISDICTION_CODE,
        "broker": BROKER
    }
    fname = f"{transfer_type}_{timestamp}.json"
    with open(proposal_dir / fname, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2)
