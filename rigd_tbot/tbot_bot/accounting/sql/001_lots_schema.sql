-- tbot_bot/accounting/sql/001_lots_schema.sql
-- Comprehensive schema for lot accounting and closures with i18n, compliance, audit, and integrity
-- Engine: SQLite

---------------------------------------
-- CONNECTION / INTEGRITY PRAGMAS
---------------------------------------
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;
PRAGMA journal_mode = WAL;
PRAGMA temp_store = MEMORY;
PRAGMA encoding = 'UTF-8';

-- Optionally tag the database for tooling (arbitrary, safe if already set)
PRAGMA application_id = 0x54424F54;     -- 'TBOT'

BEGIN;

----------------------------------------------------------------------
-- REFERENCE / LOOKUP TABLES (I18N + ORG CONTEXT)
----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ref_country (
    iso2            TEXT PRIMARY KEY,               -- 'US'
    iso3            TEXT UNIQUE,                    -- 'USA'
    name            TEXT NOT NULL,                  -- 'United States'
    numeric_code    TEXT,                           -- '840'
    region          TEXT,                           -- 'Americas'
    subregion       TEXT,                           -- 'Northern America'
    json_metadata   TEXT NOT NULL DEFAULT '{}'      -- extensibility
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ref_country_iso3 ON ref_country(iso3);

CREATE TABLE IF NOT EXISTS ref_currency (
    code            TEXT PRIMARY KEY,               -- 'USD'
    name            TEXT NOT NULL,                  -- 'United States Dollar'
    symbol          TEXT,                           -- '$'
    minor_unit      INTEGER NOT NULL DEFAULT 2,     -- decimals (2 for USD)
    json_metadata   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ref_timezone (
    iana_name       TEXT PRIMARY KEY,               -- 'America/New_York'
    utc_offset_min  INTEGER,                        -- informational only
    json_metadata   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ref_language (
    code            TEXT PRIMARY KEY,               -- 'en-US', 'en', 'fr-CA'
    name            TEXT NOT NULL,
    json_metadata   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ref_region_tag (
    tag             TEXT PRIMARY KEY,               -- e.g., 'NA', 'EU', 'APAC'
    description     TEXT,
    json_metadata   TEXT NOT NULL DEFAULT '{}'
);

-- Optional instrument catalogue (useful for reporting/joins)
CREATE TABLE IF NOT EXISTS instruments (
    symbol          TEXT PRIMARY KEY,               -- 'AAPL'
    description     TEXT,
    exchange        TEXT,                           -- e.g., 'NASDAQ'
    currency_code   TEXT REFERENCES ref_currency(code) ON UPDATE CASCADE ON DELETE SET NULL,
    country_iso2    TEXT REFERENCES ref_country(iso2) ON UPDATE CASCADE ON DELETE SET NULL,
    json_metadata   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_instruments_exchange ON instruments(exchange);

-- Context of the running bot identity (mirrors "entity_jurisdiction_broker_botid")
CREATE TABLE IF NOT EXISTS context_identity (
    entity_code         TEXT NOT NULL,
    jurisdiction_code   TEXT NOT NULL,
    broker_code         TEXT NOT NULL,
    bot_id              TEXT NOT NULL,
    default_currency    TEXT REFERENCES ref_currency(code) ON UPDATE CASCADE ON DELETE SET NULL,
    default_timezone    TEXT REFERENCES ref_timezone(iana_name) ON UPDATE CASCADE ON DELETE SET NULL,
    default_language    TEXT REFERENCES ref_language(code) ON UPDATE CASCADE ON DELETE SET NULL,
    region_tag          TEXT REFERENCES ref_region_tag(tag) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at_utc      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at_utc      TEXT NOT NULL DEFAULT (datetime('now')),
    created_by          TEXT NOT NULL DEFAULT 'system',
    updated_by          TEXT NOT NULL DEFAULT 'system',
    approval_status     TEXT NOT NULL DEFAULT 'approved' CHECK (approval_status IN ('pending','approved','rejected')),
    approved_by         TEXT,
    approved_at_utc     TEXT,
    gdpr_compliant      INTEGER NOT NULL DEFAULT 1 CHECK (gdpr_compliant IN (0,1)),
    ccpa_compliant      INTEGER NOT NULL DEFAULT 1 CHECK (ccpa_compliant IN (0,1)),
    pipeda_compliant    INTEGER NOT NULL DEFAULT 1 CHECK (pipeda_compliant IN (0,1)),
    hipaa_sensitive     INTEGER NOT NULL DEFAULT 0 CHECK (hipaa_sensitive IN (0,1)),
    iso27001_tag        TEXT,
    soc2_type           TEXT,
    json_metadata       TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (entity_code, jurisdiction_code, broker_code, bot_id)
);

----------------------------------------------------------------------
-- AUDIT TRAIL (shared, minimal viable superset)
-- NOTE: event_type is NOT NULL by design (fixes prior failures).
----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_trail (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type          TEXT NOT NULL,                 -- e.g., 'COA_LEG_REASSIGNED', 'TRADE_POSTED_LONG_BUY'
    actor               TEXT NOT NULL,                 -- username or service name
    entity_code         TEXT,
    jurisdiction_code   TEXT,
    broker_code         TEXT,
    bot_id              TEXT,
    related_table       TEXT,                          -- e.g., 'lots', 'lot_closures', 'trades'
    related_id          TEXT,                          -- row id in related_table (TEXT to allow non-integer keys)
    group_id            TEXT,
    trade_id            TEXT,
    before_json         TEXT,                          -- JSON snapshot (nullable)
    after_json          TEXT,                          -- JSON snapshot (nullable)
    reason              TEXT,
    extra_json          TEXT NOT NULL DEFAULT '{}',
    ip_address          TEXT,
    user_agent          TEXT,
    timestamp_utc       TEXT NOT NULL DEFAULT (datetime('now')),
    timezone            TEXT REFERENCES ref_timezone(iana_name) ON UPDATE CASCADE ON DELETE SET NULL,
    gdpr_compliant      INTEGER NOT NULL DEFAULT 1 CHECK (gdpr_compliant IN (0,1)),
    ccpa_compliant      INTEGER NOT NULL DEFAULT 1 CHECK (ccpa_compliant IN (0,1)),
    pipeda_compliant    INTEGER NOT NULL DEFAULT 1 CHECK (pipeda_compliant IN (0,1)),
    hipaa_sensitive     INTEGER NOT NULL DEFAULT 0 CHECK (hipaa_sensitive IN (0,1)),
    iso27001_tag        TEXT,
    soc2_type           TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_event_ts ON audit_trail(event_type, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_audit_related ON audit_trail(related_table, related_id);
CREATE INDEX IF NOT EXISTS idx_audit_identity ON audit_trail(entity_code, jurisdiction_code, broker_code, bot_id);

----------------------------------------------------------------------
-- CORE: LOTS & LOT_CLOSURES
----------------------------------------------------------------------

-- OPEN LOTS (append-only row; qty_remaining reduced by closures)
CREATE TABLE IF NOT EXISTS lots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity / context
    entity_code             TEXT NOT NULL,
    jurisdiction_code       TEXT NOT NULL,
    broker_code             TEXT NOT NULL,
    bot_id                  TEXT NOT NULL,
    FOREIGN KEY (entity_code, jurisdiction_code, broker_code, bot_id)
        REFERENCES context_identity(entity_code, jurisdiction_code, broker_code, bot_id)
        ON UPDATE CASCADE ON DELETE CASCADE,

    -- Instrument
    symbol                  TEXT NOT NULL REFERENCES instruments(symbol) ON UPDATE CASCADE ON DELETE RESTRICT,

    -- Side & quantities
    side                    TEXT NOT NULL CHECK (side IN ('long','short')),
    qty_open                REAL NOT NULL CHECK (qty_open  > 0),
    qty_remaining           REAL NOT NULL CHECK (qty_remaining >= 0 AND qty_remaining <= qty_open),

    -- Pricing & currency
    unit_cost               REAL NOT NULL CHECK (unit_cost >= 0),  -- long: cost/share; short: short-proceeds/share baseline
    fees_alloc              REAL NOT NULL DEFAULT 0 CHECK (fees_alloc >= 0),
    currency_code           TEXT NOT NULL REFERENCES ref_currency(code) ON UPDATE CASCADE ON DELETE RESTRICT,

    -- Timestamps / tz
    opened_at_utc           TEXT NOT NULL,                          -- ISO-8601 UTC
    opened_tz               TEXT REFERENCES ref_timezone(iana_name) ON UPDATE CASCADE ON DELETE SET NULL,

    -- Links
    opened_trade_id         TEXT,                                    -- broker or internal trade id
    group_id                TEXT,                                    -- optional logical group

    -- Audit / compliance
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    created_by              TEXT NOT NULL DEFAULT 'system',
    updated_by              TEXT NOT NULL DEFAULT 'system',
    approval_status         TEXT NOT NULL DEFAULT 'approved' CHECK (approval_status IN ('pending','approved','rejected')),
    approved_by             TEXT,
    approved_at_utc         TEXT,
    gdpr_compliant          INTEGER NOT NULL DEFAULT 1 CHECK (gdpr_compliant IN (0,1)),
    ccpa_compliant          INTEGER NOT NULL DEFAULT 1 CHECK (ccpa_compliant IN (0,1)),
    pipeda_compliant        INTEGER NOT NULL DEFAULT 1 CHECK (pipeda_compliant IN (0,1)),
    hipaa_sensitive         INTEGER NOT NULL DEFAULT 0 CHECK (hipaa_sensitive IN (0,1)),
    iso27001_tag            TEXT,
    soc2_type               TEXT,

    -- Extensibility
    json_metadata           TEXT NOT NULL DEFAULT '{}'
);

-- LOT CLOSURES (append-only)
CREATE TABLE IF NOT EXISTS lot_closures (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity / context (redundant denorm for reporting speed; still validatable)
    entity_code             TEXT NOT NULL,
    jurisdiction_code       TEXT NOT NULL,
    broker_code             TEXT NOT NULL,
    bot_id                  TEXT NOT NULL,
    FOREIGN KEY (entity_code, jurisdiction_code, broker_code, bot_id)
        REFERENCES context_identity(entity_code, jurisdiction_code, broker_code, bot_id)
        ON UPDATE CASCADE ON DELETE CASCADE,

    lot_id                  INTEGER NOT NULL REFERENCES lots(id) ON UPDATE CASCADE ON DELETE CASCADE,

    -- Close linkage
    close_trade_id          TEXT,                    -- broker/internal id of closing trade
    close_qty               REAL NOT NULL CHECK (close_qty > 0),

    -- Monetary components (positive magnitudes)
    basis_amount            REAL NOT NULL CHECK (basis_amount >= 0),       -- Σ(qty * unit_cost) from allocations
    proceeds_amount         REAL NOT NULL CHECK (proceeds_amount >= 0),    -- SELL cash-in or COVER cash-out
    fees_alloc              REAL NOT NULL DEFAULT 0 CHECK (fees_alloc >= 0),
    realized_pnl            REAL NOT NULL,                                  -- may be negative

    currency_code           TEXT NOT NULL REFERENCES ref_currency(code) ON UPDATE CASCADE ON DELETE RESTRICT,

    -- Timestamps / tz
    closed_at_utc           TEXT NOT NULL,
    closed_tz               TEXT REFERENCES ref_timezone(iana_name) ON UPDATE CASCADE ON DELETE SET NULL,

    -- Audit / compliance
    created_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at_utc          TEXT NOT NULL DEFAULT (datetime('now')),
    created_by              TEXT NOT NULL DEFAULT 'system',
    updated_by              TEXT NOT NULL DEFAULT 'system',
    approval_status         TEXT NOT NULL DEFAULT 'approved' CHECK (approval_status IN ('pending','approved','rejected')),
    approved_by             TEXT,
    approved_at_utc         TEXT,
    gdpr_compliant          INTEGER NOT NULL DEFAULT 1 CHECK (gdpr_compliant IN (0,1)),
    ccpa_compliant          INTEGER NOT NULL DEFAULT 1 CHECK (ccpa_compliant IN (0,1)),
    pipeda_compliant        INTEGER NOT NULL DEFAULT 1 CHECK (pipeda_compliant IN (0,1)),
    hipaa_sensitive         INTEGER NOT NULL DEFAULT 0 CHECK (hipaa_sensitive IN (0,1)),
    iso27001_tag            TEXT,
    soc2_type               TEXT,

    -- Extensibility
    json_metadata           TEXT NOT NULL DEFAULT '{}'
);

----------------------------------------------------------------------
-- OPTIONAL M:N: REGION TAGGING (extensible categorization)
----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS lot_region_tags (
    lot_id          INTEGER NOT NULL REFERENCES lots(id) ON UPDATE CASCADE ON DELETE CASCADE,
    tag             TEXT NOT NULL REFERENCES ref_region_tag(tag) ON UPDATE CASCADE ON DELETE CASCADE,
    PRIMARY KEY (lot_id, tag)
);

----------------------------------------------------------------------
-- INTEGRITY TRIGGERS (timestamps + qty bounds)
----------------------------------------------------------------------

-- Keep updated_at_utc fresh on UPDATE
CREATE TRIGGER IF NOT EXISTS trg_lots_touch_updated
AFTER UPDATE ON lots
FOR EACH ROW
BEGIN
    UPDATE lots SET updated_at_utc = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_lot_closures_touch_updated
AFTER UPDATE ON lot_closures
FOR EACH ROW
BEGIN
    UPDATE lot_closures SET updated_at_utc = datetime('now') WHERE id = NEW.id;
END;

-- Enforce qty_remaining bounds (cannot exceed qty_open; cannot go negative)
CREATE TRIGGER IF NOT EXISTS trg_lots_qty_remaining_valid
BEFORE UPDATE OF qty_remaining ON lots
FOR EACH ROW
BEGIN
    SELECT
        CASE
            WHEN NEW.qty_remaining < 0 THEN
                RAISE(ABORT, 'qty_remaining cannot be negative')
            WHEN NEW.qty_remaining > NEW.qty_open THEN
                RAISE(ABORT, 'qty_remaining cannot exceed qty_open')
        END;
END;

-- Ensure lot_closures.close_qty does not over-consume the lot (summing all closures)
-- This is a guard; application should allocate correctly, but DB will assert too.
CREATE TRIGGER IF NOT EXISTS trg_lot_closures_prevent_overclose
BEFORE INSERT ON lot_closures
FOR EACH ROW
BEGIN
    -- Ensure positive qty
    SELECT CASE WHEN NEW.close_qty <= 0 THEN RAISE(ABORT, 'close_qty must be > 0') END;

    -- Compute consumed to date for this lot
    -- If this aborts due to a missing lot row, FK will also fail, but we keep a clear message here.
    SELECT
        CASE
            WHEN (
                COALESCE((SELECT SUM(close_qty) FROM lot_closures WHERE lot_id = NEW.lot_id), 0.0)
                + NEW.close_qty
            ) > (SELECT qty_open FROM lots WHERE id = NEW.lot_id)
            THEN RAISE(ABORT, 'closure exceeds lot qty_open')
        END;
END;

----------------------------------------------------------------------
-- INDEXES (performance)
----------------------------------------------------------------------

-- Requested
CREATE INDEX IF NOT EXISTS idx_lots_symbol_side_remaining
    ON lots(symbol, side, qty_remaining);

CREATE INDEX IF NOT EXISTS idx_lot_closures_lot_id
    ON lot_closures(lot_id);

-- Additional helpful indexes
CREATE INDEX IF NOT EXISTS idx_lots_identity_symbol
    ON lots(entity_code, jurisdiction_code, broker_code, bot_id, symbol);

CREATE INDEX IF NOT EXISTS idx_lots_opened_at
    ON lots(opened_at_utc);

CREATE INDEX IF NOT EXISTS idx_lot_closures_identity
    ON lot_closures(entity_code, jurisdiction_code, broker_code, bot_id);

CREATE INDEX IF NOT EXISTS idx_lot_closures_trade
    ON lot_closures(close_trade_id);

CREATE INDEX IF NOT EXISTS idx_lot_closures_closed_at
    ON lot_closures(closed_at_utc);

----------------------------------------------------------------------
-- CONVENIENCE VIEWS (optional, read-only)
----------------------------------------------------------------------

-- Open inventory per symbol/side
CREATE VIEW IF NOT EXISTS v_open_inventory AS
SELECT
    entity_code, jurisdiction_code, broker_code, bot_id,
    symbol, side,
    SUM(qty_remaining)                AS qty_remaining,
    AVG(unit_cost)                    AS avg_unit_cost,
    MIN(opened_at_utc)                AS first_opened_utc,
    MAX(opened_at_utc)                AS last_opened_utc,
    currency_code
FROM lots
GROUP BY entity_code, jurisdiction_code, broker_code, bot_id, symbol, side, currency_code;

-- Realized P&L summary by symbol/date
CREATE VIEW IF NOT EXISTS v_realized_pnl_by_day AS
SELECT
    date(closed_at_utc)               AS close_date_utc,
    entity_code, jurisdiction_code, broker_code, bot_id,
    (SELECT currency_code FROM lots WHERE lots.id = lot_closures.lot_id) AS currency_code,
    (SELECT symbol FROM lots WHERE lots.id = lot_closures.lot_id)        AS symbol,
    SUM(realized_pnl)                 AS realized_pnl,
    SUM(proceeds_amount)              AS proceeds_total,
    SUM(basis_amount)                 AS basis_total,
    SUM(fees_alloc)                   AS fees_total
FROM lot_closures
GROUP BY close_date_utc, entity_code, jurisdiction_code, broker_code, bot_id, symbol, currency_code;

----------------------------------------------------------------------
-- SEED MINIMAL LOOKUPS (safe if already present)
----------------------------------------------------------------------

INSERT OR IGNORE INTO ref_currency(code, name, symbol, minor_unit) VALUES
 ('USD','United States Dollar','$',2),
 ('EUR','Euro','€',2),
 ('GBP','Pound Sterling','£',2);

INSERT OR IGNORE INTO ref_timezone(iana_name, utc_offset_min) VALUES
 ('UTC',0),
 ('America/New_York',-300),
 ('America/Chicago',-360),
 ('America/Denver',-420),
 ('America/Los_Angeles',-480);

INSERT OR IGNORE INTO ref_language(code, name) VALUES
 ('en','English'),
 ('en-US','English (United States)');

COMMIT;
