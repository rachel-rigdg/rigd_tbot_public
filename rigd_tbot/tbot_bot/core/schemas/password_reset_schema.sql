-- core/schema/password_reset_schema.sql
-- Fully expanded, maximum-completeness schema for password reset token storage
-- Includes full auditability, compliance, localization, and extensibility

PRAGMA foreign_keys = ON;

-- Main table to store password reset tokens and metadata
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    user_id INTEGER NOT NULL,                             -- FK to system_users.id
    reset_token TEXT UNIQUE NOT NULL,                     -- Secure token (UUID or hash)
    token_type TEXT CHECK(token_type IN ('email', 'sms', 'mfa', 'backup')) NOT NULL DEFAULT 'email',
    expiration_timestamp TEXT NOT NULL,                   -- UTC expiry timestamp (ISO 8601)
    used BOOLEAN DEFAULT 0,                               -- Flag if token has already been used
    used_at TEXT,                                         -- UTC timestamp when token was redeemed
    request_ip TEXT NOT NULL CHECK(length(request_ip) >= 7), -- IP address of token requestor
    user_agent TEXT,                                      -- Optional user-agent string
    device_fingerprint TEXT,                              -- Optional hashed device ID
    request_platform TEXT,                                -- OS or platform used for request
    delivery_method TEXT CHECK(delivery_method IN ('email', 'sms', 'other')), -- How token was sent
    
    country_code TEXT NOT NULL CHECK(length(country_code) = 2), -- ISO 3166-1 alpha-2
    region TEXT,                                           -- State/province/region
    timezone TEXT NOT NULL,                                -- Olson-style timezone
    language_code TEXT NOT NULL CHECK(length(language_code) = 2), -- ISO 639-1 language
    currency_code TEXT NOT NULL CHECK(length(currency_code) = 3), -- ISO 4217 currency

    compliance_gdpr BOOLEAN DEFAULT 0,
    compliance_ccpa BOOLEAN DEFAULT 0,
    compliance_pipeda BOOLEAN DEFAULT 0,
    compliance_hipaa BOOLEAN DEFAULT 0,
    compliance_iso BOOLEAN DEFAULT 0,
    compliance_soc2 BOOLEAN DEFAULT 0,

    approved_by TEXT,
    approval_timestamp TEXT,

    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    deleted BOOLEAN DEFAULT 0,
    deletion_reason TEXT,

    json_metadata TEXT DEFAULT '{}',
    extra_fields TEXT DEFAULT '{}',

    FOREIGN KEY(user_id) REFERENCES system_users(id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

-- Audit log of token generation, use, and deletion
CREATE TABLE IF NOT EXISTS password_reset_token_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL,
    
    action TEXT NOT NULL CHECK(action IN ('generated', 'used', 'expired', 'deleted', 'resent')),
    action_description TEXT,
    changed_by TEXT NOT NULL,
    change_timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    change_ip TEXT,
    geo_location TEXT,
    
    compliance_reviewed BOOLEAN DEFAULT 0,
    compliance_notes TEXT,
    json_metadata TEXT,
    extra_fields TEXT,

    FOREIGN KEY(token_id) REFERENCES password_reset_tokens(id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

-- Lookup reference table for reset token types
CREATE TABLE IF NOT EXISTS password_reset_method_reference (
    method_code TEXT PRIMARY KEY,
    method_name TEXT NOT NULL,
    description TEXT NOT NULL,
    is_mfa BOOLEAN DEFAULT 0,
    supported_regions TEXT,  -- Optional list or JSON
    compliance_flags TEXT,
    created_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_by TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    json_metadata TEXT,
    extra_fields TEXT
);

-- Indexes for token lookup and compliance filters
CREATE INDEX IF NOT EXISTS idx_reset_tokens_user ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_expiry ON password_reset_tokens(expiration_timestamp);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_used ON password_reset_tokens(used);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_compliance ON password_reset_tokens(
    compliance_gdpr, compliance_ccpa, compliance_hipaa, compliance_soc2
);
CREATE INDEX IF NOT EXISTS idx_audit_token ON password_reset_token_audit(token_id);
