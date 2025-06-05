-- core/schemas/ledger_status_schema.sql  
-- Fully expanded, maximum-completeness schema for ledger status tracking with internationalization, compliance, extensibility, and audit-readiness

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ledgers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_code TEXT NOT NULL UNIQUE,
    ledger_name TEXT NOT NULL,
    description TEXT,
    entity_id INTEGER NOT NULL,
    currency_code TEXT NOT NULL,
    country_code TEXT NOT NULL,
    region_code TEXT,
    timezone TEXT,
    language_code TEXT,
    ledger_type TEXT CHECK(ledger_type IN ('general', 'subledger', 'special_purpose')),
    regulatory_tags TEXT,
    compliance_notes TEXT,
    json_metadata TEXT,
    extra_fields TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES intercompany_entities(id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS ledger_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_id INTEGER NOT NULL,
    status_date DATE NOT NULL,
    status TEXT CHECK(status IN ('open', 'closed', 'archived', 'locked', 'pending_approval')) NOT NULL,
    closing_balance DECIMAL(20, 6),
    currency_code TEXT NOT NULL,
    notes TEXT,
    regulatory_tags TEXT,
    compliance_flags TEXT,
    compliance_notes TEXT,
    json_metadata TEXT,
    extra_fields TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_by TEXT,
    approved_at TIMESTAMP,
    FOREIGN KEY (ledger_id) REFERENCES ledgers(id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS ledger_status_audit_trails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_status_id INTEGER NOT NULL,
    change_type TEXT CHECK(change_type IN ('created', 'updated', 'approved', 'locked', 'unlocked', 'deleted')),
    change_details TEXT,
    changed_by TEXT,
    change_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    change_ip TEXT,
    geo_location TEXT,
    compliance_reviewed BOOLEAN DEFAULT 0,
    compliance_notes TEXT,
    json_metadata TEXT,
    extra_fields TEXT,
    FOREIGN KEY (ledger_status_id) REFERENCES ledger_status(id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX idx_ledger_status_ledger ON ledger_status (ledger_id);
CREATE INDEX idx_ledger_status_audit_trails_status ON ledger_status_audit_trails (ledger_status_id);
