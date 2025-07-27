# tbot_bot/accounting/ledger_modules/ledger_compliance_filter.py

"""
Ledger compliance filter for validating transactions before they are written to the ledger.
Used by sync, holdings, and all modules that create or import ledger entries.
"""

PRIMARY_FIELDS = ("symbol", "datetime_utc", "action", "price", "quantity", "total_value")

def is_compliant_ledger_entry(entry: dict) -> bool:
    """
    Returns True if entry is valid for ledger write.
    Rejects partial/invalid/blank/zero-value trades and known placeholder/canceled orders.
    """
    # Must have all primary fields non-empty
    for field in PRIMARY_FIELDS:
        val = entry.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            return False

    # price and quantity must be positive
    try:
        if float(entry.get("price", 0)) <= 0:
            return False
        if float(entry.get("quantity", 0)) <= 0:
            return False
        if float(entry.get("total_value", 0)) <= 0:
            return False
    except Exception:
        return False

    # Exclude canceled/rejected orders, placeholders, or entries with status
    status = entry.get("status", "").lower()
    if status in ("canceled", "cancelled", "rejected", "pending_cancel", "expired"):
        return False

    # Exclude test entries, missing trade_id, or missing action
    if entry.get("trade_id") in (None, "", "None"):
        return False
    if entry.get("action", "").lower() in ("", "none", "test"):
        return False

    return True
