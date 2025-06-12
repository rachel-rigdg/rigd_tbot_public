-- tbot_bot/accounting/tbot_ledger_schema.sql
-- PRODUCTION-GRADE, MAXIMUM-COMPLETENESS LEDGER SCHEMA (INTERNATIONAL, AUDIT, COMPLIANCE, EXTENSIBLE)

PRAGMA foreign_keys = ON;

-- Reference Table: Countries
CREATE TABLE IF NOT EXISTS countries (
    code TEXT PRIMARY KEY,                             -- ISO 3166-1 alpha-2 country code
    name TEXT NOT NULL,
    region TEXT NOT NULL,                              -- Continent or regional classification (ISO 3166-2/UN)
    timezone TEXT NOT NULL,                            -- Default time zone (IANA)
    currency_code TEXT NOT NULL,                       -- ISO 4217 currency code
    language_code TEXT DEFAULT 'en',                   -- Default language (ISO 639-1)
    json_metadata TEXT DEFAULT '{}'
);

-- Reference Table: Currencies
CREATE TABLE IF NOT EXISTS currencies (
    code TEXT PRIMARY KEY,                             -- ISO 4217 currency code
    name TEXT NOT NULL,
    symbol TEXT,
    fraction_digits INTEGER DEFAULT 2,
    json_metadata TEXT DEFAULT '{}'
);

-- Reference Table: Languages
CREATE TABLE IF NOT EXISTS languages (
    code TEXT PRIMARY KEY,                             -- ISO 639-1 language code
    name TEXT NOT NULL,
    region TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Reference Table: Regions
CREATE TABLE IF NOT EXISTS regions (
    code TEXT PRIMARY KEY,                             -- UN M.49 or custom
    name TEXT NOT NULL,
    parent_region TEXT,
    json_metadata TEXT DEFAULT '{}'
);

-- Reference Table: Jurisdictions
CREATE TABLE IF NOT EXISTS jurisdictions (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT,
    compliance_profile TEXT,                           -- e.g. GDPR, CCPA
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
    account_json TEXT NOT NULL,                         -- Root/top-level node JSON
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

-- Table: Ledger Entries (primary table, transaction log)
CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    datetime_utc TEXT NOT NULL,                         -- ISO-8601 UTC timestamp
    entry_type TEXT NOT NULL,                           -- e.g. "trade", "deposit", "withdrawal", "fee", "adjustment", etc
    symbol TEXT,                                        -- e.g. Stock, ETF, FX pair
    action TEXT CHECK(action IN ('buy', 'sell', 'long', 'short', 'put', 'call', 'dividend', 'interest', 'fee', 'transfer', 'other')) NOT NULL,
    quantity REAL CHECK(quantity >= 0.0),
    price REAL CHECK(price >= 0.0),
    amount REAL NOT NULL,                               -- Signed amount (credit+/debit-)
    total_value REAL,                                   -- Absolute (for reporting)
    currency_code TEXT NOT NULL REFERENCES currencies(code),
    account_code TEXT,                                  -- e.g. COA code (links to COA)
    counterparty TEXT,                                  -- Broker/counterparty info
    trade_id TEXT UNIQUE,                               -- Broker trade/external ID
    broker TEXT,
    strategy TEXT,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    jurisdiction TEXT,
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
    json_metadata TEXT DEFAULT '{}'
);

-- Table: Trades (normalized view of ledger_entries, for legacy code/support)
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_entry_id INTEGER REFERENCES ledger_entries(id) ON DELETE CASCADE,
    datetime_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT CHECK(action IN ('long', 'short', 'put', 'inverse')) NOT NULL,
    quantity REAL CHECK(quantity >= 0.0) NOT NULL,
    price REAL CHECK(price >= 0.0) NOT NULL,
    total_value REAL NOT NULL,
    fees REAL DEFAULT 0.0 CHECK(fees >= 0.0),
    broker TEXT NOT NULL,
    strategy TEXT CHECK(strategy IN ('open', 'mid', 'close', 'other')) DEFAULT 'other',
    account TEXT NOT NULL,
    trade_id TEXT UNIQUE NOT NULL,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    jurisdiction TEXT,
    entity_code TEXT NOT NULL,
    language TEXT DEFAULT 'en',
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
    json_metadata TEXT DEFAULT '{}',
    FOREIGN KEY (ledger_entry_id) REFERENCES ledger_entries(id) ON DELETE CASCADE
);

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
    jurisdiction TEXT,
    language TEXT DEFAULT 'en',
    created_by TEXT DEFAULT 'system',
    updated_by TEXT DEFAULT NULL,
    resolved_by TEXT DEFAULT NULL,
    resolution_notes TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT NULL,
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
    json_metadata TEXT DEFAULT '{}'
);

-- Table: Float Allocation History (capital floats)
CREATE TABLE IF NOT EXISTS float_allocation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    broker TEXT NOT NULL,
    allocated_amount REAL NOT NULL,
    reason TEXT,
    allocated_by TEXT,
    approved_by TEXT,
    approved_on TEXT,
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

-- Cross-table Relationships (for future expansion)
-- (e.g., FOREIGN KEY (entity_code) REFERENCES entities(code) ON DELETE SET NULL, ...)

