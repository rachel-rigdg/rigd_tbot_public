-- core/schemas/system_logs_schema.sql
-- Fully expanded, maximum-completeness schema for system logs with internationalization, compliance, extensibility, and auditability

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_type TEXT CHECK(log_type IN ('info', 'warning', 'error', 'debug', 'audit', 'security')) NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    system_module TEXT,
    subsystem TEXT,
    country_code TEXT,
    region TEXT,
    language_code TEXT DEFAULT 'en',
    timezone TEXT DEFAULT 'UTC',
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    severity TEXT CHECK(severity IN ('low', 'medium', 'high', 'critical')) DEFAULT 'medium',
    user_id INTEGER,
    source_ip TEXT,
    geo_location TEXT,
    device_fingerprint TEXT,
    compliance_flags TEXT, -- e.g., 'GDPR_violation, SOC2_alert'
    json_metadata JSON,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_resolved BOOLEAN DEFAULT 0,
    resolution_notes TEXT,
    resolved_by TEXT,
    resolved_at TIMESTAMP,
    is_archived BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS system_log_audit_trails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id INTEGER NOT NULL,
    change_type TEXT CHECK(change_type IN ('created', 'updated', 'resolved', 'archived', 'deleted')),
    change_details TEXT,
    changed_by TEXT NOT NULL,
    change_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    change_ip TEXT,
    geo_location TEXT,
    compliance_reviewed BOOLEAN DEFAULT 0,
    compliance_notes TEXT,
    extra_metadata JSON,
    FOREIGN KEY (log_id) REFERENCES system_logs(id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX idx_system_logs_type ON system_logs(log_type);
CREATE INDEX idx_system_logs_severity ON system_logs(severity);
CREATE INDEX idx_system_logs_module ON system_logs(system_module);
CREATE INDEX idx_system_logs_occurred_at ON system_logs(occurred_at);
CREATE INDEX idx_system_log_audit_trails_log ON system_log_audit_trails(log_id);
