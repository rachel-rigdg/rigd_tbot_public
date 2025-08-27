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

# Canonical audit trail schema (append-only JSONL). Must be a superset of all audit events.
AUDIT_TRAIL_FIELDS = [
    "ts_utc",                # ISO8601 UTC timestamp
    "event",                 # e.g., 'coa_reassign', 'opening_balance_posted', etc.
    "actor",                 # username or system actor
    "entry_id",              # affected trades.id (if applicable)
    "group_id",              # logical group identifier
    "trade_id",              # external trade id (if applicable)
    "old_account_code",      # prior COA code (when reassigning)
    "new_account_code",      # new COA code (when reassigning)
    "reason",                # free-form reason/comment
    "entity_code",
    "jurisdiction_code",
    "broker_code",
    "bot_id",
    "sync_run_id",           # sync correlation id (if any)
    "source",                # 'inline_edit', 'sync', 'migration', etc.
    "notes",                 # optional extra notes
    "request_id",            # optional correlation id from web/API
    "ip",                    # optional client ip (web)
    "user_agent",            # optional UA (web)
    "extra"                  # JSON blob for additional structured context
]
