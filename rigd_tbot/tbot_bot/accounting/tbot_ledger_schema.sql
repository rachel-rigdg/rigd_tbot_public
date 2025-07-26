-- tbot_bot/accounting/tbot_ledger_schema.sql
-- PRODUCTION-GRADE, MAXIMUM-COMPLETENESS LEDGER SCHEMA (INTERNATIONAL, AUDIT, COMPLIANCE, EXTENSIBLE)

PRAGMA foreign_keys = ON;

-- Reference Table: Countries
CREATE TABLE IF NOT EXISTS countries (
    code TEXT PRIMARY KEY,                              -- ISO 3166-1 alpha-2 country code
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    timezone TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    language_code TEXT DEFAULT 'en',
    json_metadata TEXT DEFAULT '{}'
);

-- Reference Table: Currencies
CREATE TABLE IF NOT EXISTS currencies (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    symbol TEXT,
    fraction_digits INTEGER DEFAULT 2,
    json_metadata TEXT DEFAULT '{}'
);

-- Reference Table: Languages
CREATE TABLE IF NOT EXISTS languages (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Reference Table: Regions
CREATE TABLE IF NOT EXISTS regions (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_region TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Reference Table: Jurisdictions
CREATE TABLE IF NOT EXISTS jurisdictions (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT,
    compliance_profile TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Table: Brokers (reference table for all integrated brokers)
CREATE TABLE IF NOT EXISTS brokers (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT REFERENCES countries(code),
    timezone TEXT,
    contact TEXT,
    compliance TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Table: COA Metadata (Chart of Accounts)
CREATE TABLE IF NOT EXISTS coa_metadata (
    currency_code TEXT NOT NULL REFERENCES currencies(code),
    entity_code TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(code),
    coa_version TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    last_updated_utc TEXT NOT NULL,
    language_code TEXT DEFAULT 'en',
    json_metadata TEXT DEFAULT '{}'
);

-- Table: COA Accounts (hierarchical as JSON)
CREATE TABLE IF NOT EXISTS coa_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_json TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL,
    coa_version TEXT NOT NULL,
    created_by TEXT DEFAULT 'system',
    updated_by TEXT DEFAULT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT NULL,
    language_code TEXT DEFAULT 'en',
    json_metadata TEXT DEFAULT '{}'
);

-- Table: Ledger Entries
CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    datetime_utc TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    symbol TEXT,
    symbol_full TEXT,
    isin TEXT,
    cusip TEXT,
    sedol TEXT,
    figi TEXT,
    action TEXT CHECK(action IN (
        'buy', 'sell', 'long', 'short', 'put', 'call', 'dividend', 'interest',
        'fee', 'transfer', 'other', 'exercise', 'assignment', 'split', 'expire',
        'journal', 'contribution', 'distribution', 'withhold', 'correction', 'reorg', 'tax', 'foreign_fx'
    )) NOT NULL,
    trade_id TEXT,
    broker_code TEXT NOT NULL REFERENCES brokers(code),
    account_code TEXT,
    account_id TEXT,
    sub_account TEXT,
    quantity REAL CHECK(quantity >= 0.0),
    quantity_type TEXT,
    price REAL CHECK(price >= 0.0),
    price_currency TEXT REFERENCES currencies(code),
    amount REAL NOT NULL,
    total_value REAL,
    currency_code TEXT NOT NULL REFERENCES currencies(code),
    fx_rate REAL,
    commission REAL DEFAULT 0.0 CHECK(commission >= 0.0),
    commission_currency TEXT REFERENCES currencies(code),
    fee REAL DEFAULT 0.0 CHECK(fee >= 0.0),
    fee_currency TEXT REFERENCES currencies(code),
    accrued_interest REAL DEFAULT 0.0,
    accrued_interest_currency TEXT REFERENCES currencies(code),
    tax REAL DEFAULT 0.0,
    tax_currency TEXT REFERENCES currencies(code),
    net_amount REAL,
    settlement_date TEXT,
    trade_date TEXT,
    description TEXT,
    counterparty TEXT,
    strategy TEXT,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(code),
    entity_code TEXT NOT NULL,
    language_code TEXT DEFAULT 'en',
    created_by TEXT DEFAULT 'system',
    updated_by TEXT DEFAULT NULL,
    approved_by TEXT DEFAULT NULL,
    approval_status TEXT CHECK(approval_status IN ('pending', 'approved', 'rejected')) DEFAULT 'approved',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT NULL,
    gdpr_compliant BOOLEAN DEFAULT 1,
    ccpa_compliant BOOLEAN DEFAULT 1,
    pipeda_compliant BOOLEAN DEFAULT 1,
    hipaa_sensitive BOOLEAN DEFAULT 0,
    iso27001_tag TEXT DEFAULT '',
    soc2_type TEXT DEFAULT '',
    extra_fields TEXT DEFAULT '{}',
    json_metadata TEXT DEFAULT '{}',
    bot_id TEXT DEFAULT NULL
);

-- Table: Trades (normalized view, legacy, for bot-internal trade logic)
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_entry_id INTEGER REFERENCES ledger_entries(id) ON DELETE CASCADE,
    datetime_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    symbol_full TEXT,
    action TEXT CHECK(action IN ('long', 'short', 'put', 'inverse', 'call', 'assignment', 'exercise', 'expire', 'reorg')) NOT NULL,
    quantity REAL CHECK(quantity >= 0.0) NOT NULL,
    quantity_type TEXT,
    price REAL CHECK(price >= 0.0) NOT NULL,
    total_value REAL NOT NULL,
    amount REAL NOT NULL,
    side TEXT CHECK(side IN ('debit','credit')) NOT NULL,
    commission REAL DEFAULT 0.0 CHECK(commission >= 0.0),
    fee REAL DEFAULT 0.0 CHECK(fee >= 0.0),
    broker_code TEXT NOT NULL REFERENCES brokers(code),
    account TEXT NOT NULL,
    trade_id TEXT NOT NULL,
    group_id TEXT, -- Optionally used for grouping double-entry pairs
    strategy TEXT,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(code),
    entity_code TEXT NOT NULL,
    language TEXT DEFAULT 'en',
    created_by TEXT DEFAULT 'system',
    updated_by TEXT DEFAULT NULL,
    approved_by TEXT DEFAULT NULL,
    approval_status TEXT CHECK(approval_status IN ('pending', 'approved', 'rejected')) DEFAULT 'approved',
    status TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT NULL,
    gdpr_compliant BOOLEAN DEFAULT 1,
    ccpa_compliant BOOLEAN DEFAULT 1,
    pipeda_compliant BOOLEAN DEFAULT 1,
    hipaa_sensitive BOOLEAN DEFAULT 0,
    iso27001_tag TEXT DEFAULT '',
    soc2_type TEXT DEFAULT '',
    currency_code TEXT,
    language_code TEXT DEFAULT 'en',
    price_currency TEXT,
    fx_rate REAL,
    commission_currency TEXT,
    fee_currency TEXT,
    accrued_interest REAL DEFAULT 0.0,
    accrued_interest_currency TEXT,
    tax REAL DEFAULT 0.0,
    tax_currency TEXT,
    net_amount REAL,
    settlement_date TEXT,
    trade_date TEXT,
    description TEXT,
    counterparty TEXT,
    sub_account TEXT,
    extra_fields TEXT DEFAULT '{}',
    json_metadata TEXT DEFAULT '{}',
    bot_id TEXT DEFAULT NULL,
    FOREIGN KEY (ledger_entry_id) REFERENCES ledger_entries(id) ON DELETE CASCADE
);

-- Index for (trade_id, side) to support deduplication and quick double-entry lookup
CREATE INDEX IF NOT EXISTS idx_trades_tradeid_side ON trades (trade_id, side);
-- Table: Events (compliance, audit, info/warning/error)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time_utc TEXT NOT NULL,
    type TEXT CHECK(type IN ('Info', 'Warning', 'Error', 'Export', 'System', 'Compliance')) NOT NULL,
    related_trade_id TEXT,
    related_ledger_entry_id INTEGER REFERENCES ledger_entries(id) ON DELETE SET NULL,
    message TEXT NOT NULL,
    account TEXT NOT NULL,
    severity TEXT CHECK(severity IN ('Minor', 'Moderate', 'Critical')) NOT NULL,
    entity_code TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(code),
    language TEXT DEFAULT 'en',
    created_by TEXT DEFAULT 'system',
    updated_by TEXT DEFAULT NULL,
    resolved_by TEXT DEFAULT NULL,
    resolution_notes TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT NULL,
    extra_fields TEXT DEFAULT '{}',
    json_metadata TEXT DEFAULT '{}',
    FOREIGN KEY (related_trade_id) REFERENCES trades(trade_id) ON DELETE SET NULL ON UPDATE CASCADE
);

-- Table: Ledger Lock State (concurrent access control)
CREATE TABLE IF NOT EXISTS ledger_lock_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_name TEXT NOT NULL UNIQUE,
    locked BOOLEAN NOT NULL DEFAULT 0,
    locked_by TEXT,
    lock_reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT NULL,
    extra_fields TEXT DEFAULT '{}',
    json_metadata TEXT DEFAULT '{}'
);

-- Table: Float Allocation History (capital floats)
CREATE TABLE IF NOT EXISTS float_allocation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(code),
    broker_code TEXT NOT NULL REFERENCES brokers(code),
    allocated_amount REAL NOT NULL,
    reason TEXT,
    allocated_by TEXT,
    approved_by TEXT,
    approved_on TEXT,
    extra_fields TEXT DEFAULT '{}',
    json_metadata TEXT DEFAULT '{}'
);

-- Table: Audit Trail (full change log)
CREATE TABLE IF NOT EXISTS audit_trail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    related_table TEXT,
    related_id INTEGER,
    action TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    actor TEXT NOT NULL,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    context TEXT,
    gdpr_compliant BOOLEAN DEFAULT 1,
    ccpa_compliant BOOLEAN DEFAULT 1,
    pipeda_compliant BOOLEAN DEFAULT 1,
    hipaa_sensitive BOOLEAN DEFAULT 0,
    iso27001_tag TEXT DEFAULT '',
    soc2_type TEXT DEFAULT '',
    extra_fields TEXT DEFAULT '{}',
    json_metadata TEXT DEFAULT '{}'
);

-- Table: External Statements (broker imports)
CREATE TABLE IF NOT EXISTS external_statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_code TEXT NOT NULL REFERENCES brokers(code),
    account_id TEXT,
    statement_date TEXT NOT NULL,
    import_source TEXT,
    import_format TEXT,
    import_file TEXT,
    imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
    imported_by TEXT,
    status TEXT CHECK(status IN ('pending', 'imported', 'error')) DEFAULT 'pending',
    error_message TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Table: External Transactions (raw broker transaction import log)
CREATE TABLE IF NOT EXISTS external_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_statement_id INTEGER REFERENCES external_statements(id) ON DELETE CASCADE,
    broker_code TEXT NOT NULL REFERENCES brokers(code),
    trade_id TEXT,
    datetime_utc TEXT,
    symbol TEXT,
    symbol_full TEXT,
    action TEXT,
    quantity REAL,
    price REAL,
    amount REAL,
    currency_code TEXT,
    commission REAL,
    fee REAL,
    net_amount REAL,
    description TEXT,
    notes TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Table: Account Balances (per-broker, per-entity, per-currency)
CREATE TABLE IF NOT EXISTS account_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_code TEXT NOT NULL REFERENCES brokers(code),
    entity_code TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(code),
    account_id TEXT,
    currency_code TEXT NOT NULL REFERENCES currencies(code),
    balance REAL NOT NULL,
    as_of_datetime_utc TEXT NOT NULL,
    notes TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Table: Option Contracts (for detailed option trade reporting)
CREATE TABLE IF NOT EXISTS option_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    symbol_full TEXT,
    underlying TEXT,
    expiration TEXT,
    strike REAL,
    option_type TEXT CHECK(option_type IN ('put', 'call')),
    multiplier REAL DEFAULT 100.0,
    currency_code TEXT REFERENCES currencies(code),
    exchange TEXT,
    broker_code TEXT REFERENCES brokers(code),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT NULL,
    json_metadata TEXT DEFAULT '{}'
);

-- Table: Reconciliation Log (ledger vs. broker statement)
CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_code TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(code),
    broker_code TEXT NOT NULL REFERENCES brokers(code),
    account_id TEXT,
    statement_date TEXT,
    ledger_balance REAL,
    broker_balance REAL,
    delta REAL,
    status TEXT CHECK(status IN ('pending', 'matched', 'mismatched', 'resolved')),
    resolution TEXT,
    resolved_by TEXT,
    resolved_at TEXT,
    notes TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Compound Indexes & Foreign Key Indexes

CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades (symbol, datetime_utc);
CREATE INDEX IF NOT EXISTS idx_trades_entity ON trades (entity_code);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades (strategy);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_datetime ON ledger_entries (datetime_utc, entry_type);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_entity ON ledger_entries (entity_code);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (type, event_time_utc);
CREATE INDEX IF NOT EXISTS idx_events_entity ON events (entity_code);
CREATE INDEX IF NOT EXISTS idx_float_allocation_by_date ON float_allocation_history (date, entity_code);
CREATE INDEX IF NOT EXISTS idx_audit_trail_event_type ON audit_trail (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_trail_timestamp ON audit_trail (timestamp);
CREATE INDEX IF NOT EXISTS idx_extstat_broker_date ON external_statements (broker_code, statement_date);
CREATE INDEX IF NOT EXISTS idx_exttrans_broker_tradeid ON external_transactions (broker_code, trade_id);
CREATE INDEX IF NOT EXISTS idx_acct_balances_broker_entity ON account_balances (broker_code, entity_code, currency_code);
CREATE INDEX IF NOT EXISTS idx_option_contracts_symbol ON option_contracts (symbol, expiration, strike, option_type);
