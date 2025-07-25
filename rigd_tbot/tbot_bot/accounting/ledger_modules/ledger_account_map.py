# tbot_bot/accounting/ledger_modules/ledger_account_map.py

from cryptography.fernet import Fernet
from pathlib import Path
import json

ACCOUNT_MAP = {
    "cash": "Assets:Brokerage Accounts – Equities:Cash",
    "equity": "Assets:Brokerage Accounts – Equities",
    "gain": "Income:Realized Gains",
    "fee": "Expenses:Broker fee",
    "slippage": "Expenses:Slippage / Execution Losses",
    "failures": "System Integrity:Failures & Rejected Orders",
    "infra": "Expenses:Bot Infrastructure Costs",
    "float_ledger": "Equity:Capital Float Ledger",
    "float_history": "Equity:Daily Float Allocation History",
    "retained": "Equity:Accumulated Profit",
    "opening": "Equity:Opening Balance",
    "meta_trade": "Logging / Execution References:Trade UUID",
    "meta_strategy": "Logging / Execution References:Strategy Tag",
    "meta_recon": "Logging / Execution References:Reconciliation Passed Flag",
    "meta_lock": "System Integrity:Ledger Lock Flag (YES/NO)"
}

def get_account_path(key):
    return ACCOUNT_MAP.get(key, "")

def load_broker_code():
    key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "bot_identity.key"
    enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "bot_identity.json.enc"
    key = key_path.read_bytes()
    cipher = Fernet(key)
    plaintext = cipher.decrypt(enc_path.read_bytes())
    bot_identity_data = json.loads(plaintext.decode("utf-8"))
    identity = bot_identity_data.get("BOT_IDENTITY_STRING")
    return identity.split("_")[2]

def load_account_number():
    try:
        key_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "keys" / "acct_api.key"
        enc_path = Path(__file__).resolve().parents[3] / "tbot_bot" / "storage" / "secrets" / "acct_api.json.enc"
        key = key_path.read_bytes()
        cipher = Fernet(key)
        plaintext = cipher.decrypt(enc_path.read_bytes())
        acct_api_data = json.loads(plaintext.decode("utf-8"))
        return acct_api_data.get("ACCOUNT_NUMBER", "") or acct_api_data.get("ACCOUNT_ID", "")
    except Exception:
        return ""
