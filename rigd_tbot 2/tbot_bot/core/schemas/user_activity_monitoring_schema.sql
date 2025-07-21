-- rigd_accounting/core/schemas/user_activity_monitoring_schema.sql
-- Tracks all user activity with full auditability, compliance tagging, localization, and extensible metadata

PRAGMA foreign_keys = ON;

-- Table to log all user activity events across the system
CREATE TABLE IF NOT EXISTS user_activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    user_id INTEGER NOT NULL,                                -- Foreign key to system_users.id
    session_id TEXT NOT NULL,                                -- Unique session identifier
    action_type TEXT NOT NULL CHECK (length(action_type) > 1), -- e.g., "LOGIN", "LOGOUT", "VIEW", "MODIFY"
    action_target TEXT,                                      -- Optional target of action (e.g., "ledger_id:203")
    action_description TEXT,                                 -- Full description of the action performed
    
    entity_code TEXT NOT NULL,                               -- e.g., "RGL"
    jurisdiction_code TEXT NOT NULL,                         -- e.g., "USA"

    ip_address TEXT NOT NULL CHECK (length(ip_address) >= 7),-- Captured IP address (IPv4 or IPv6)
    user_agent TEXT,                                         -- Optional user-agent string from browser or API client
    device_fingerprint TEXT,                                 -- Optional hashed fingerprint of client device
    platform TEXT,                                           -- OS, environment, or execution platform

    country_code TEXT NOT NULL CHECK (length(country_code) = 2), -- ISO 3166-1 alpha-2
    region TEXT,                                             -- State/province/region
    timezone TEXT NOT NULL,                                  -- Olson-style timezone, e.g., "America/Los_Angeles"
    language_code TEXT NOT NULL CHECK (length(language_code) = 2), -- ISO 639-1 (e.g., "en")
    currency_code TEXT NOT NULL CHECK (length(currency_code) = 3), -- ISO 4217 (e.g., "USD")

    compliance_gdpr BOOLEAN NOT NULL DEFAULT 0,              -- Tagged for GDPR review or compliance trace
    compliance_ccpa BOOLEAN NOT NULL DEFAULT 0,              -- Tagged for CCPA compliance
    compliance_pipeda BOOLEAN NOT NULL DEFAULT 0,            -- Tagged for PIPEDA
    compliance_hipaa BOOLEAN NOT NULL DEFAULT 0,             -- Tagged for HIPAA sensitivity
    compliance_iso BOOLEAN NOT NULL DEFAULT 0,               -- General ISO 27001 trace flag
    compliance_soc2 BOOLEAN NOT NULL DEFAULT 0,              -- Tagged for SOC 2 Type II relevance
    
    approved_by TEXT,                                        -- Optional approval authority
    approval_timestamp TEXT,                                 -- UTC timestamp of approval action

    created_at TEXT NOT NULL DEFAULT (datetime('now')),      -- Timestamp of event (UTC)
    created_by TEXT NOT NULL,                                -- Username or agent who created the entry
    updated_at TEXT,                                         -- Last modification timestamp (if ever)
    updated_by TEXT,                                         -- Last modifying user (if any)
    
    is_deleted BOOLEAN NOT NULL DEFAULT 0,                   -- Soft-delete flag
    deletion_reason TEXT,                                    -- If soft-deleted, reason is stored here
    
    json_metadata TEXT DEFAULT '{}',                         -- JSON-encoded blob for extensible metadata
    extra_fields TEXT DEFAULT '{}',                          -- Reserved for future extensibility

    FOREIGN KEY(user_id) REFERENCES system_users(id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

-- Lookup table for activity types and severity classification
CREATE TABLE IF NOT EXISTS activity_type_reference (
    action_type TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    default_severity TEXT NOT NULL CHECK (default_severity IN ('LOW','MEDIUM','HIGH','CRITICAL'))
);

-- Audit trail of modifications to user_activity_log (append-only)
CREATE TABLE IF NOT EXISTS user_activity_log_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id INTEGER NOT NULL,
    
    old_action_type TEXT,
    new_action_type TEXT,
    
    old_action_description TEXT,
    new_action_description TEXT,

    old_updated_by TEXT,
    new_updated_by TEXT,
    
    change_timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    change_by TEXT NOT NULL,
    reason_for_change TEXT NOT NULL CHECK (length(reason_for_change) > 5),

    FOREIGN KEY(original_id) REFERENCES user_activity_log(id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

-- Compound index to optimize queries by user, action, and time
CREATE INDEX IF NOT EXISTS idx_user_activity_main ON user_activity_log (
    user_id, action_type, created_at
);

-- Compound index for regional compliance lookup
CREATE INDEX IF NOT EXISTS idx_user_activity_compliance ON user_activity_log (
    compliance_gdpr, compliance_ccpa, compliance_pipeda, compliance_hipaa
);
