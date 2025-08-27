-- tbot_bot/accounting/ledger_modules/schema.sql
-- Overlay/migration: enforce required constraints and metadata without redefining baseline tables.
-- - UNIQUE(fitid, broker_code) (where applicable)
-- - FK(legs→groups) via triggers if table FK not present
-- - CHECK domain on side IN ('debit','credit') via triggers
-- - Meta table for opening_balances_posted flag and schema version

PRAGMA foreign_keys = ON;
PRAGMA recursive_triggers = ON;

BEGIN;

-- 1) Meta table (append-only style key/value)
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

-- Initialize required meta keys if missing
INSERT OR IGNORE INTO meta(key, value) VALUES ('opening_balances_posted', 'false');
INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', 'v048-ledger-modules-1');

-- 2) Safety: ensure trade_groups has unique group_id for FK enforcement
--    (No-op if already PK/UNIQUE)
CREATE UNIQUE INDEX IF NOT EXISTS ux_trade_groups_group_id ON trade_groups(group_id);

-- 3) UNIQUE(fitid, broker_code) on trades when both are present
--    (Conditional unique via partial index to avoid NULL collisions)
CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_fitid_broker
ON trades(fitid, broker_code)
WHERE fitid IS NOT NULL AND broker_code IS NOT NULL;

-- 4) Emulate FK(trades.group_id → trade_groups.group_id) with triggers
--    (SQLite cannot add FKs to existing table without rebuild; triggers enforce integrity)

-- Insert FK check
CREATE TRIGGER IF NOT EXISTS trg_trades_group_fk_ins
BEFORE INSERT ON trades
WHEN NEW.group_id IS NOT NULL
  AND (SELECT COUNT(1) FROM trade_groups WHERE group_id = NEW.group_id) = 0
BEGIN
  SELECT RAISE(ABORT, 'FK violation: trades.group_id → trade_groups.group_id');
END;

-- Update FK check
CREATE TRIGGER IF NOT EXISTS trg_trades_group_fk_upd
BEFORE UPDATE OF group_id ON trades
WHEN NEW.group_id IS NOT NULL
  AND (SELECT COUNT(1) FROM trade_groups WHERE group_id = NEW.group_id) = 0
BEGIN
  SELECT RAISE(ABORT, 'FK violation: trades.group_id → trade_groups.group_id');
END;

-- 5) CHECK domain for debit/credit side
--    Enforce that side is either 'debit' or 'credit' if provided (NULL allowed for legacy rows)

-- Insert side check
CREATE TRIGGER IF NOT EXISTS trg_trades_side_chk_ins
BEFORE INSERT ON trades
WHEN NEW.side IS NOT NULL AND NEW.side NOT IN ('debit','credit')
BEGIN
  SELECT RAISE(ABORT, 'CHECK violation: trades.side must be debit or credit');
END;

-- Update side check
CREATE TRIGGER IF NOT EXISTS trg_trades_side_chk_upd
BEFORE UPDATE OF side ON trades
WHEN NEW.side IS NOT NULL AND NEW.side NOT IN ('debit','credit')
BEGIN
  SELECT RAISE(ABORT, 'CHECK violation: trades.side must be debit or credit');
END;

COMMIT;
