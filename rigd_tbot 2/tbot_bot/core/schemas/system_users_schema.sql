-- core/schemas/system_users_schema.sql
-- Fully expanded, maximum-completeness schema for system users with internationalization, compliance, audit, and extensibility

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS system_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    display_name TEXT,
    role TEXT CHECK(role IN ('admin', 'editor', 'viewer', 'auditor', 'superuser')) NOT NULL,
    locale TEXT, -- e.g., 'en_US', 'de_DE'
    country_code TEXT, -- ISO 3166-1 alpha-2
    timezone TEXT, -- e.g., 'UTC', 'America/New_York'
    preferred_currency TEXT, -- e.g., 'USD', 'EUR'
    preferred_language TEXT, -- ISO 639-1 code
    phone_number TEXT,
    mfa_enabled BOOLEAN DEFAULT 0,
    mfa_method TEXT CHECK(mfa_method IN ('totp', 'sms', 'email', 'hardware_key')),
    account_status TEXT CHECK(account_status IN ('active', 'inactive', 'locked', 'pending')) DEFAULT 'active',
    last_login_at TIMESTAMP,
    last_login_ip TEXT,
    failed_login_attempts INTEGER DEFAULT 0,
    password_changed_at TIMESTAMP,
    terms_accepted BOOLEAN DEFAULT 0,
    terms_accepted_at TIMESTAMP,
    regulatory_tags TEXT, -- e.g., 'GDPR, CCPA, HIPAA'
    compliance_flags TEXT, -- e.g., 'requires_review, restricted_access'
    json_metadata TEXT, -- additional extensible fields (JSON)
    extra_fields TEXT, -- additional notes or structured data
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_locked BOOLEAN DEFAULT 0,
    UNIQUE(username, email)
);

CREATE TABLE IF NOT EXISTS user_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_name TEXT UNIQUE NOT NULL,
    description TEXT,
    permissions TEXT, -- comma-separated or JSON list of permissions
    country_code TEXT,
    regulatory_scope TEXT, -- e.g., 'GDPR, SOC2'
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    compliance_notes TEXT,
    json_metadata TEXT,
    extra_fields TEXT
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_token TEXT UNIQUE NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    geo_location TEXT,
    login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    logout_at TIMESTAMP,
    session_status TEXT CHECK(session_status IN ('active', 'expired', 'terminated')) DEFAULT 'active',
    mfa_verified BOOLEAN DEFAULT 0,
    regulatory_tags TEXT,
    json_metadata TEXT,
    FOREIGN KEY (user_id) REFERENCES system_users(id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS user_audit_trails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    action_details TEXT,
    performed_by TEXT,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT,
    geo_location TEXT,
    compliance_reviewed BOOLEAN DEFAULT 0,
    compliance_notes TEXT,
    json_metadata TEXT,
    FOREIGN KEY (user_id) REFERENCES system_users(id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS user_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    permission TEXT NOT NULL,
    granted_by TEXT,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    compliance_notes TEXT,
    json_metadata TEXT,
    FOREIGN KEY (user_id) REFERENCES system_users(id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX idx_system_users_role ON system_users(role);
CREATE INDEX idx_system_users_status ON system_users(account_status);
CREATE INDEX idx_user_sessions_status ON user_sessions(session_status);
CREATE INDEX idx_user_audit_trails_action ON user_audit_trails(action);
CREATE INDEX idx_user_permissions_permission ON user_permissions(permission);
