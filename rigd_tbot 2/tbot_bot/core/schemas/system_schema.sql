-- core/schemas/system_schema.sql  
-- Fully expanded, maximum-completeness schema for system configuration, internationalization, compliance, extensibility, and auditability

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS system_configuration (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key TEXT NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    description TEXT,
    category TEXT,
    country_code TEXT,
    region TEXT,
    language_code TEXT DEFAULT 'en',
    timezone TEXT DEFAULT 'UTC',
    is_active BOOLEAN DEFAULT 1,
    effective_from TIMESTAMP,
    effective_until TIMESTAMP,
    compliance_flags TEXT, -- e.g., 'GDPR, SOC2, ISO27001'
    json_metadata JSON,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name TEXT NOT NULL UNIQUE,
    description TEXT,
    service_type TEXT CHECK(service_type IN ('core', 'auxiliary', 'integration')),
    status TEXT CHECK(status IN ('active', 'inactive', 'deprecated', 'maintenance')) DEFAULT 'active',
    version TEXT,
    deployment_environment TEXT CHECK(deployment_environment IN ('development', 'staging', 'production')),
    country_code TEXT,
    region TEXT,
    language_code TEXT DEFAULT 'en',
    timezone TEXT DEFAULT 'UTC',
    compliance_tags TEXT,
    json_metadata JSON,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL,
    check_type TEXT CHECK(check_type IN ('heartbeat', 'latency', 'uptime', 'security', 'compliance')),
    status TEXT CHECK(status IN ('pass', 'warn', 'fail')),
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response_time_ms INTEGER,
    result_details TEXT,
    compliance_flags TEXT,
    json_metadata JSON,
    FOREIGN KEY (service_id) REFERENCES system_services(id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS system_audit_trails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT CHECK(entity_type IN ('configuration', 'service', 'health_check')),
    entity_id INTEGER NOT NULL,
    change_type TEXT CHECK(change_type IN ('created', 'updated', 'deleted', 'activated', 'deactivated')),
    change_details TEXT,
    changed_by TEXT NOT NULL,
    change_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    change_ip TEXT,
    geo_location TEXT,
    compliance_reviewed BOOLEAN DEFAULT 0,
    compliance_notes TEXT,
    extra_metadata JSON
);

CREATE INDEX idx_system_config_key ON system_configuration(config_key);
CREATE INDEX idx_system_services_name ON system_services(service_name);
CREATE INDEX idx_system_health_service ON system_health_checks(service_id);
CREATE INDEX idx_system_audit_entity ON system_audit_trails(entity_type, entity_id);
