# tbot_bot/accounting/ledger_modules/ledger_fields.py

"""
Central canonical field lists for all ledger-related tables.
Import these lists everywhere to ensure schema alignment and prevent drift.

NOTE: TRADES_FIELDS order must match the SQLite schema exactly (PRAGMA table_info(trades))
excluding the autoincrement primary key 'id'.
"""

TRADES_FIELDS = [
    # -- must match trades schema columns 1..56 (id omitted) --
    "ledger_entry_id",
    "datetime_utc",
    "symbol",
    "symbol_full",
    "action",
    "quantity",
    "quantity_type",
    "price",
    "total_value",
    "amount",
    "side",
    "commission",
    "fee",
    "broker_code",
    "account",
    "trade_id",
    "group_id",                  # critical for grouping/UI
    "strategy",
    "tags",
    "notes",
    "jurisdiction_code",
    "entity_code",
    "language",
    "created_by",
    "updated_by",
    "approved_by",
    "approval_status",
    "status",
    "created_at",
    "updated_at",
    "gdpr_compliant",
    "ccpa_compliant",
    "pipeda_compliant",
    "hipaa_sensitive",
    "iso27001_tag",
    "soc2_type",
    "currency_code",
    "language_code",
    "price_currency",
    "fx_rate",
    "commission_currency",
    "fee_currency",
    "accrued_interest",
    "accrued_interest_currency",
    "tax",
    "tax_currency",
    "net_amount",
    "settlement_date",
    "trade_date",
    "description",
    "counterparty",
    "sub_account",
    "extra_fields",
    "json_metadata",
    "raw_broker_json",
    "bot_id",
]

LEDGER_ENTRIES_FIELDS = [
    "datetime_utc", "entry_type", "symbol", "symbol_full", "isin", "cusip", "sedol", "figi", "action", "trade_id",
    "broker_code", "account_code", "account_id", "sub_account", "quantity", "quantity_type", "price", "price_currency",
    "amount", "total_value", "currency_code", "fx_rate", "commission", "commission_currency", "fee", "fee_currency",
    "accrued_interest", "accrued_interest_currency", "tax", "tax_currency", "net_amount", "settlement_date",
    "trade_date", "description", "counterparty", "strategy", "tags", "notes", "jurisdiction_code", "entity_code",
    "language_code", "created_by", "updated_by", "approved_by", "approval_status", "created_at", "updated_at",
    "gdpr_compliant", "ccpa_compliant", "pipeda_compliant", "hipaa_sensitive", "iso27001_tag", "soc2_type",
    "extra_fields", "json_metadata", "raw_broker_json", "bot_id"
]

RECONCILIATION_LOG_FIELDS = [
    "id", "trade_id", "entity_code", "jurisdiction_code", "broker_code", "broker", "error_code", "account_id",
    "statement_date", "ledger_balance", "ledger_entry_id", "broker_balance", "delta", "status", "resolution",
    "resolved_by", "resolved_at", "raw_record", "notes", "recon_type", "raw_record_json", "compare_fields",
    "json_metadata", "timestamp_utc", "sync_run_id", "api_hash", "imported_at", "updated_at", "user_action", "mapping_version"
]

# Allowed action values for normalized trade actions
ALLOWED_TRADE_ACTIONS = [
    "long", "short", "put", "inverse", "call", "assignment", "exercise", "expire", "reorg", "other"
]

# Canonical audit trail schema used by ledger_audit.log_audit_event().
# Keep these names in sync with the INSERT keys there and the audit_trail table.
AUDIT_TRAIL_FIELDS = [
    "timestamp",           # ISO8601 UTC timestamp
    "action",              # e.g., 'coa_reassign', 'opening_balance_posted', etc.
    "related_id",          # affected trades.id / ledger entry id (if applicable)
    "actor",               # username or system actor
    "old_value",           # JSON (string) of previous state (nullable)
    "new_value",           # JSON (string) of new state (nullable)
    # Context / optional columns (safe to be NULL)
    "entity_code",
    "jurisdiction_code",
    "broker_code",
    "bot_id",
    "group_id",
    "trade_id",
    "sync_run_id",
    "source",              # 'inline_edit', 'sync', 'migration', etc.
    "notes",
    "request_id",
    "ip",
    "user_agent",
    "extra"                # JSON blob for additional structured context
]
