# tbot_bot/accounting/ledger_modules/ledger_fields.py

"""
Central canonical field lists for all ledger-related tables.
Import these lists everywhere to ensure schema alignment and prevent drift.
"""

TRADES_FIELDS = [
    "ledger_entry_id", "datetime_utc", "symbol", "symbol_full", "action", "side", "quantity", "quantity_type",
    "price", "total_value", "amount", "commission", "commission_currency", "fee", "fee_currency", "currency_code",
    "language_code", "price_currency", "fx_rate", "accrued_interest", "accrued_interest_currency", "tax",
    "tax_currency", "net_amount", "settlement_date", "trade_date", "description", "counterparty", "sub_account",
    "broker_code", "strategy", "account", "trade_id", "tags", "notes", "jurisdiction_code", "entity_code",
    "language", "created_by", "updated_by", "approved_by", "approval_status", "gdpr_compliant", "ccpa_compliant",
    "pipeda_compliant", "hipaa_sensitive", "iso27001_tag", "soc2_type", "extra_fields", "json_metadata", "bot_id",
    "created_at", "updated_at", "status"
]

LEDGER_ENTRIES_FIELDS = [
    "datetime_utc", "entry_type", "symbol", "symbol_full", "isin", "cusip", "sedol", "figi", "action", "trade_id",
    "broker_code", "account_code", "account_id", "sub_account", "quantity", "quantity_type", "price", "price_currency",
    "amount", "total_value", "currency_code", "fx_rate", "commission", "commission_currency", "fee", "fee_currency",
    "accrued_interest", "accrued_interest_currency", "tax", "tax_currency", "net_amount", "settlement_date",
    "trade_date", "description", "counterparty", "strategy", "tags", "notes", "jurisdiction_code", "entity_code",
    "language_code", "created_by", "updated_by", "approved_by", "approval_status", "created_at", "updated_at",
    "gdpr_compliant", "ccpa_compliant", "pipeda_compliant", "hipaa_sensitive", "iso27001_tag", "soc2_type",
    "extra_fields", "json_metadata", "bot_id"
]
