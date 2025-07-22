# tbot_bot/accounting/ledger.py

import sqlite3
from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_web.support.auth_web import get_current_user  # to get current user for updated_by etc.
from tbot_bot.accounting.ledger_utils import load_broker_code, load_account_number, get_account_path

def get_identity_tuple():
    identity = load_bot_identity()
    return tuple(identity.split("_"))

def load_internal_ledger():
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT id, ledger_entry_id, datetime_utc, symbol, action, quantity, price, total_value, fees, broker, "
        "strategy, account, trade_id, tags, notes, jurisdiction, entity_code, language, "
        "created_by, updated_by, approved_by, approval_status, gdpr_compliant, ccpa_compliant, "
        "pipeda_compliant, hipaa_sensitive, iso27001_tag, soc2_type, created_at, updated_at, "
        "CASE WHEN approval_status = 'approved' THEN 'ok' ELSE 'mismatch' END AS status, json_metadata "
        "FROM trades"
    )
    results = []
    for row in cursor.fetchall():
        results.append({
            "id": row[0],
            "ledger_entry_id": row[1],
            "datetime_utc": row[2],
            "symbol": row[3],
            "action": row[4],
            "quantity": row[5],
            "price": row[6],
            "total_value": row[7],
            "fees": row[8],
            "broker": row[9],
            "strategy": row[10],
            "account": row[11],
            "trade_id": row[12],
            "tags": row[13],
            "notes": row[14],
            "jurisdiction": row[15],
            "entity_code": row[16],
            "language": row[17],
            "created_by": row[18],
            "updated_by": row[19],
            "approved_by": row[20],
            "approval_status": row[21],
            "gdpr_compliant": row[22],
            "ccpa_compliant": row[23],
            "pipeda_compliant": row[24],
            "hipaa_sensitive": row[25],
            "iso27001_tag": row[26],
            "soc2_type": row[27],
            "created_at": row[28],
            "updated_at": row[29],
            "status": row[30],
            "json_metadata": row[31],
        })
    conn.close()
    return results

def mark_entry_resolved(entry_id):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    current_user = get_current_user()
    updater = (
        current_user.username if hasattr(current_user, "username")
        else current_user if current_user else "system"
    )
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE trades SET approval_status = 'approved', updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (updater, entry_id)
    )
    conn.commit()
    conn.close()

def add_ledger_entry(entry_data):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    # Inject backend-only account and broker
    entry_data["broker"] = load_broker_code()
    entry_data["account"] = load_account_number()
    # Robust backend total_value calculation
    try:
        qty = float(entry_data.get("quantity") or 0)
        price = float(entry_data.get("price") or 0)
        fees = float(entry_data.get("fees") or 0)
        entry_data["total_value"] = round((qty * price) - fees, 2)
    except Exception:
        entry_data["total_value"] = entry_data.get("total_value") or 0
    columns = [
        "ledger_entry_id", "datetime_utc", "symbol", "action", "quantity", "price", "total_value", "fees", "broker",
        "strategy", "account", "trade_id", "tags", "notes", "jurisdiction", "entity_code", "language",
        "created_by", "updated_by", "approved_by", "approval_status", "gdpr_compliant", "ccpa_compliant",
        "pipeda_compliant", "hipaa_sensitive", "iso27001_tag", "soc2_type", "json_metadata"
    ]
    values = [entry_data.get(col) for col in columns]
    placeholders = ", ".join("?" for _ in columns)
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    conn.close()

def edit_ledger_entry(entry_id, updated_data):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    # Always override backend-only account and broker
    updated_data["broker"] = load_broker_code()
    updated_data["account"] = load_account_number()
    # Backend-side robust total_value calculation
    try:
        qty = float(updated_data.get("quantity") or 0)
        price = float(updated_data.get("price") or 0)
        fees = float(updated_data.get("fees") or 0)
        updated_data["total_value"] = round((qty * price) - fees, 2)
    except Exception:
        updated_data["total_value"] = updated_data.get("total_value") or 0
    columns = [
        "ledger_entry_id", "datetime_utc", "symbol", "action", "quantity", "price", "total_value", "fees", "broker",
        "strategy", "account", "trade_id", "tags", "notes", "jurisdiction", "entity_code", "language",
        "updated_by", "approval_status", "gdpr_compliant", "ccpa_compliant", "pipeda_compliant",
        "hipaa_sensitive", "iso27001_tag", "soc2_type", "json_metadata"
    ]
    set_clause = ", ".join([f"{col}=?" for col in columns])
    values = [updated_data.get(col) for col in columns]
    values.append(entry_id)
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"UPDATE trades SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values
    )
    conn.commit()
    conn.close()

def delete_ledger_entry(entry_id):
    bot_identity = get_identity_tuple()
    db_path = resolve_ledger_db_path(*bot_identity)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "DELETE FROM trades WHERE id = ?",
        (entry_id,)
    )
    conn.commit()
    conn.close()

# --- Holdings/Float/Reserve/Tax/Payroll/Rebalance Hooks ---

def post_tax_reserve_entry(amount, datetime_utc, notes=None):
    """
    Posts a tax reserve allocation entry to the ledger.
    """
    entry = {
        "ledger_entry_id": None,
        "datetime_utc": datetime_utc,
        "symbol": None,
        "action": "reserve_tax",
        "quantity": None,
        "price": None,
        "total_value": amount,
        "fees": 0,
        "broker": load_broker_code(),
        "strategy": "TAX_RESERVE",
        "account": get_account_path("tax_reserve"),
        "trade_id": None,
        "tags": "tax,reserve",
        "notes": notes or "",
        "jurisdiction": None,
        "entity_code": None,
        "language": "en",
        "created_by": get_current_user() or "system",
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
    }
    add_ledger_entry(entry)

def post_payroll_reserve_entry(amount, datetime_utc, notes=None):
    """
    Posts a payroll reserve allocation entry to the ledger.
    """
    entry = {
        "ledger_entry_id": None,
        "datetime_utc": datetime_utc,
        "symbol": None,
        "action": "reserve_payroll",
        "quantity": None,
        "price": None,
        "total_value": amount,
        "fees": 0,
        "broker": load_broker_code(),
        "strategy": "PAYROLL_RESERVE",
        "account": get_account_path("payroll_reserve"),
        "trade_id": None,
        "tags": "payroll,reserve",
        "notes": notes or "",
        "jurisdiction": None,
        "entity_code": None,
        "language": "en",
        "created_by": get_current_user() or "system",
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
    }
    add_ledger_entry(entry)

def post_float_allocation_entry(amount, datetime_utc, notes=None):
    """
    Posts a float allocation entry to the ledger.
    """
    entry = {
        "ledger_entry_id": None,
        "datetime_utc": datetime_utc,
        "symbol": None,
        "action": "float_allocation",
        "quantity": None,
        "price": None,
        "total_value": amount,
        "fees": 0,
        "broker": load_broker_code(),
        "strategy": "FLOAT_ALLOCATION",
        "account": get_account_path("float_ledger"),
        "trade_id": None,
        "tags": "float,allocation",
        "notes": notes or "",
        "jurisdiction": None,
        "entity_code": None,
        "language": "en",
        "created_by": get_current_user() or "system",
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
    }
    add_ledger_entry(entry)

def post_rebalance_entry(symbol, amount, action, datetime_utc, notes=None):
    """
    Posts a rebalance action entry to the ledger.
    """
    entry = {
        "ledger_entry_id": None,
        "datetime_utc": datetime_utc,
        "symbol": symbol,
        "action": f"rebalance_{action}",
        "quantity": None,
        "price": None,
        "total_value": amount,
        "fees": 0,
        "broker": load_broker_code(),
        "strategy": "REBALANCE",
        "account": get_account_path("equity"),
        "trade_id": None,
        "tags": f"rebalance,{action}",
        "notes": notes or "",
        "jurisdiction": None,
        "entity_code": None,
        "language": "en",
        "created_by": get_current_user() or "system",
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
    }
    add_ledger_entry(entry)
