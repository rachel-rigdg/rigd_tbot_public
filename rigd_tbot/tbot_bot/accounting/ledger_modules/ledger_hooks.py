# tbot_bot/accounting/ledger_modules/ledger_hooks.py

from tbot_bot.accounting.ledger_modules.ledger_account_map import get_account_path, load_broker_code
from tbot_web.support.auth_web import get_current_user
from tbot_bot.accounting.ledger_modules.ledger_double_entry import post_ledger_entries_double_entry
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS

def _build_entry(custom_fields):
    entry = {k: None for k in TRADES_FIELDS}
    entry.update(custom_fields)
    return entry

def post_tax_reserve_entry(amount, datetime_utc, notes=None):
    entry = _build_entry({
        "ledger_entry_id": None,
        "datetime_utc": datetime_utc,
        "symbol": None,
        "action": "reserve_tax",
        "side": "debit",
        "quantity": None,
        "price": None,
        "total_value": amount,
        "fee": 0,
        "broker_code": load_broker_code(),
        "strategy": "TAX_RESERVE",
        "account": get_account_path("tax_reserve"),
        "trade_id": None,
        "tags": "tax,reserve",
        "notes": notes or "",
        "jurisdiction_code": None,
        "entity_code": None,
        "language": "en",
        "created_by": getattr(get_current_user(), "username", None) or "system",
        "updated_by": None,
        "approved_by": None,
        "approval_status": "pending",
        "gdpr_compliant": True,
        "ccpa_compliant": True,
        "pipeda_compliant": False,
        "hipaa_sensitive": False,
        "iso27001_tag": None,
        "soc2_type": None,
        "json_metadata": "{}"
    })
    post_ledger_entries_double_entry([entry])

def post_payroll_reserve_entry(amount, datetime_utc, notes=None):
    entry = _build_entry({
        "ledger_entry_id": None,
        "datetime_utc": datetime_utc,
        "symbol": None,
        "action": "reserve_payroll",
        "side": "debit",
        "quantity": None,
        "price": None,
        "total_value": amount,
        "fee": 0,
        "broker_code": load_broker_code(),
        "strategy": "PAYROLL_RESERVE",
        "account": get_account_path("payroll_reserve"),
        "trade_id": None,
        "tags": "payroll,reserve",
        "notes": notes or "",
        "jurisdiction_code": None,
        "entity_code": None,
        "language": "en",
        "created_by": getattr(get_current_user(), "username", None) or "system",
        "updated_by": None,
        "approved_by": None,
        "approval_status": "pending",
        "gdpr_compliant": True,
        "ccpa_compliant": True,
        "pipeda_compliant": False,
        "hipaa_sensitive": False,
        "iso27001_tag": None,
        "soc2_type": None,
        "json_metadata": "{}"
    })
    post_ledger_entries_double_entry([entry])

def post_float_allocation_entry(amount, datetime_utc, notes=None):
    entry = _build_entry({
        "ledger_entry_id": None,
        "datetime_utc": datetime_utc,
        "symbol": None,
        "action": "float_allocation",
        "side": "debit",
        "quantity": None,
        "price": None,
        "total_value": amount,
        "fee": 0,
        "broker_code": load_broker_code(),
        "strategy": "FLOAT_ALLOCATION",
        "account": get_account_path("float_ledger"),
        "trade_id": None,
        "tags": "float,allocation",
        "notes": notes or "",
        "jurisdiction_code": None,
        "entity_code": None,
        "language": "en",
        "created_by": getattr(get_current_user(), "username", None) or "system",
        "updated_by": None,
        "approved_by": None,
        "approval_status": "pending",
        "gdpr_compliant": True,
        "ccpa_compliant": True,
        "pipeda_compliant": False,
        "hipaa_sensitive": False,
        "iso27001_tag": None,
        "soc2_type": None,
        "json_metadata": "{}"
    })
    post_ledger_entries_double_entry([entry])

def post_rebalance_entry(symbol, amount, action, datetime_utc, notes=None):
    entry = _build_entry({
        "ledger_entry_id": None,
        "datetime_utc": datetime_utc,
        "symbol": symbol,
        "action": f"rebalance_{action}",
        "side": "debit",
        "quantity": None,
        "price": None,
        "total_value": amount,
        "fee": 0,
        "broker_code": load_broker_code(),
        "strategy": "REBALANCE",
        "account": get_account_path("equity"),
        "trade_id": None,
        "tags": f"rebalance,{action}",
        "notes": notes or "",
        "jurisdiction_code": None,
        "entity_code": None,
        "language": "en",
        "created_by": getattr(get_current_user(), "username", None) or "system",
        "updated_by": None,
        "approved_by": None,
        "approval_status": "pending",
        "gdpr_compliant": True,
        "ccpa_compliant": True,
        "pipeda_compliant": False,
        "hipaa_sensitive": False,
        "iso27001_tag": None,
        "soc2_type": None,
        "json_metadata": "{}"
    })
    post_ledger_entries_double_entry([entry])
