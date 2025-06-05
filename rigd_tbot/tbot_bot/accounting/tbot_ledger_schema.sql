-- tbot_bot/accounting/tbot_ledger_schema.sql
-- SQL reference for ledger structure – comprehensive, extensible, and audit-ready

PRAGMA foreign_keys = ON;

-- Table: countries
CREATE TABLE IF NOT EXISTS countries (
    code TEXT PRIMARY KEY,                     -- ISO 3166-1 alpha-2 country code
    name TEXT NOT NULL,
    region TEXT,                               -- Optional: continent or regional classification
    timezone TEXT NOT NULL,                    -- Default time zone (IANA)
    currency_code TEXT NOT NULL                -- ISO 4217 currency code
);

-- Table: coa_metadata (COA required metadata fields)
CREATE TABLE IF NOT EXISTS coa_metadata (
    currency_code TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    jurisdiction_code TEXT NOT NULL,
    coa_version TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    last_updated_utc TEXT NOT NULL
);

-- Table: coa_accounts (COA hierarchical structure as JSON)
CREATE TABLE IF NOT EXISTS coa_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_json TEXT NOT NULL                 -- JSON for each root/top-level account node
);

-- Table: trades
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    datetime_utc TEXT NOT NULL,                -- ISO-8601 timestamp (UTC)
    symbol TEXT NOT NULL,                      -- Stock or ETF ticker
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
    jurisdiction TEXT,                         -- Jurisdiction tag for compliance
    entity_code TEXT NOT NULL,                 -- Associated entity code (e.g., RGL)
    language TEXT DEFAULT 'en',                -- ISO 639-1 language code
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

-- Table: events
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time_utc TEXT NOT NULL,
    type TEXT CHECK(type IN ('Info', 'Warning', 'Error', 'Export', 'System', 'Compliance')) NOT NULL,
    related_trade_id TEXT,
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

-- Table: ledger_lock_state
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

-- Table: float_allocation_history
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

-- Table: audit_trail
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
    json_metadata TEXT DEFAULT '{}'
);

-- Indexes for trades
CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades (symbol, datetime_utc);
CREATE INDEX IF NOT EXISTS idx_trades_entity ON trades (entity_code);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades (strategy);

-- Indexes for events
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (type, event_time_utc);
CREATE INDEX IF NOT EXISTS idx_events_entity ON events (entity_code);

-- Indexes for float_allocation_history
CREATE INDEX IF NOT EXISTS idx_float_allocation_by_date ON float_allocation_history (date, entity_code);

-- Indexes for audit_trail
CREATE INDEX IF NOT EXISTS idx_audit_trail_event_type ON audit_trail (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_trail_timestamp ON audit_trail (timestamp);
