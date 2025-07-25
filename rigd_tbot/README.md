==============================
Objective 
==============================

TradeBot (TBot) is a fully automated intraday trading system that executes bi-directional trades using long equity for bullish signals and inverse ETFs or long puts for bearish signals, strictly determined by `SHORT_TYPE_*` values in `.env_bot`. All broker integrations must support long equity and at least one approved bearish instrument (long put or inverse ETF) for every assignment.

All strategies operate in real time with risk-weighted execution, enforcing all risk controls exclusively via `.env_bot` parameters: `DAILY_LOSS_LIMIT`, `MAX_RISK_PER_TRADE`, `TOTAL_ALLOCATION`, `MAX_OPEN_POSITIONS`, and all strategy/broker enablement toggles. **All trade output is immutably logged to OFX-compliant, entity-scoped SQLite ledgers, enforcing double-entry and UTC timestamps.**

**Bootstrap Process:**
- Bootstrap is only initiated via a required Web UI configuration submission (`configuration.html`) which invokes `configuration_web.py` and all required `init_*.py` scripts.
- **No CLI-based or automated provisioning is permitted**: creation of users, credentials, system logs, bot identity, and Chart of Accounts (COA) may only be performed via the Web UI.
- COA is self-contained, managed, and versioned solely via the dedicated COA Management page in the tbot_web UI. **No CLI or accounting system COA pushes are allowed.**
- COA metadata (`coa_metadata` table) must include all required fields and be managed and validated via `utils_coa_web.py` and `coa_utils_ledger.py`.

**Ledger and Trade Routing:**
- All execution toggles must be set in `.env_bot`: `ALPACA_ENABLED`, `IBKR_ENABLED`, `STRAT_OPEN_ENABLED`, `STRAT_MID_ENABLED`, `STRAT_CLOSE_ENABLED`.
- All trade and PnL activity is written to `{ENTITY_CODE}_{JURISDICTION_CODE}_{BROKER_CODE}_{BOT_ID}_BOT_ledger.db` with path and metadata resolved only at session start from locally decrypted config files (`.env_bot.enc`, `bot_identity.json.enc`). **No runtime injection or modification from external systems is permitted.**
- Each ledger write is always preceded by a timestamped backup.
- No ledger or float updates are managed by the bot from any external source; all runtime references are internal only.

**Accounting & Float:**
- The accounting system reads/export ledgers after session completion for audit, reporting, or reconciliation.
- Float injections, reserves, and transfers are externally managed (never by bot); bot only logs float deviation/rebalance events.
- All float, broker, and config metadata are resolved at session start from local config. No runtime modifications.

**PnL, float tracking, and revenue movement** are only ingested, reconciled, and logged by accounting after session completion. **TEST_MODE is deprecated and removed. All test routines must execute strictly via the `tbot_bot/test/` suite.**

==============================
System Instructions (Strict Enforcement)
==============================

1. All env/config values **MUST** be loaded only from `.env`, `.env_enc`, `.env_bot`, `.env_bot.enc`. No hardcoded secrets, toggles, paths, or runtime injection. Suppressed/disabled states must be explicitly checked.
2. Inline comments are REQUIRED in all generated code, especially for logic branches, `.env_bot` usage, and condition paths.
3. All paths must be relative and platform-agnostic (macOS/Linux/Cloud).
4. Ledger routing: All trade activity writes to OFX-compliant, entity-scoped SQLite ledgers. Filename: `{ENTITY_CODE}_{JURISDICTION_CODE}_{account_name}_{BROKER_CODE}_{BOT_ID}_BOT_ledger.db`. Ledger path, float, and all metadata resolved from config at session start. **No external ledger writes or bypass allowed. All ledger writes are preceded by a backup.** Test modules may simulate trades but NEVER bypass or alter production ledger logic.
5. **No re-ingestion of CSV/JSON logs is permitted**—all logs are for audit export only.
6. Each strategy module must implement `.self_check()`. `main.py` must halt if any self check fails, logging the reason, strategy, and UTC timestamp.
7. `env_bot.py` must validate all required keys from `.env_bot.enc`, decrypted with `storage/keys/env.key`. Missing/malformed keys must raise fatal startup error.
8. All logs and ledger outputs include: `timestamp`, `strategy_name`, `ticker`, `side`, `size`, `entry_price`, `exit_price`, `PnL`, `broker`, `error_code` (if applicable). Log format is globally set by `LOG_FORMAT` in `.env_bot`.
9. `VERSION.md` is required and must document version, logic/structure changes, and deltas.
10. **All tbot_bot modules must be executable independently.** No core trading logic may import from Flask or `tbot_web/`. Web UI and core trading logic are decoupled. All bootstrap scripts are executed **only** by the Web UI via `configuration.html`/`configuration_web.py`. **No CLI-based bootstrap allowed.**
11. All strategy and broker routing is toggled solely via `.env_bot` settings.
12. The COA is fully managed via the tbot_web UI, versioned and validated, and present as both a JSON structure and in the `coa_metadata` table in all ledgers. All UI operations must use `utils_coa_web.py`; all schema/ledger checks must use `coa_utils_ledger.py`.
13. Improvisation is forbidden. Clarify all ambiguities before code changes.

================================================================================
Deployment/Runtime Notes 
================================================================================

- All scripts/paths must be cross-platform (macOS, Linux, cloud).
- `tbot_bot/` must run independently of `tbot_web/`.
- Log and ledger output is always live, regardless of UI status.
- Only one broker is enabled at a time.
- All broker API keys from `.env`/`.env_bot` must validate at startup.
- Strategy enable/disable toggles: `STRAT_OPEN_ENABLED`, `STRAT_MID_ENABLED`, `STRAT_CLOSE_ENABLED`.
- Pre-trade validation (strict):
  - Market spread ≤ 1.5% of entry price
  - Volume ≥ `MIN_VOLUME_THRESHOLD`
  - No violations of `MAX_RISK_PER_TRADE` or `DAILY_LOSS_LIMIT`
- Auto-shutdown on:
  - Broker API failure (`watchdog_bot.py`)
  - Critical runtime error (`error_handler.py`)
  - Loss breach (`kill_switch.py`)
- Ledger writes: `entities/{ENTITY}_{JURIS}_{account}_{BROKER}_{BOT_ID}_BOT_ledger.db` (OFX-compliant).
- Each ledger write is preceded by a timestamped backup in `entities/{ENTITY}_{JURIS}/backups/`.
- OFX exports only via `/export/generate_ofx.py`.
- Log files: `/output/logs/open.log`, `/mid.log`, `/close.log`, `/unresolved_orders.log`
- Post-session logs may be zipped/archived (`auto_backup.py`).
- Optional: cloud sync via `scripts/upload_backups_to_cloud.sh`.
- Backups never block live ledger writes.
- Session timing and trading days (from `.env_bot`) must be strictly respected.

--------------------------------------------------------------------------------
COA/Schema Enforcement 
--------------------------------------------------------------------------------

- All ledgers **must** match `tbot_ledger_schema.sql` and `tbot_ledger_coa_template.json`.
- `coa_metadata` table must include: `currency_code`, `entity_code`, `jurisdiction_code`, `coa_version`, `created_at_utc`, `last_updated_utc`.
- Schema or COA mismatch detected by `build_check.py` or ledger init must halt the bot and log a fatal error.
- COA is managed exclusively via tbot_web UI (`coa_web.py`, `coa.html`), never from accounting or CLI.
- Human-readable COA exports are only via web UI to `/output/ledgers/`.
- All new ledgers must initialize the COA table at creation and lock for double-entry enforcement.
- All account transactions must be validated against the COA at entry.
- All UI COA operations: `utils_coa_web.py`; ledger/schema: `coa_utils_ledger.py`.

================================================================================
Time Zone Standards
================================================================================

- All time values, logs, strategy triggers, ledger entries, and alerts are UTC—system-wide enforcement.
- Strategy start times (`START_TIME_*`) in `.env_bot` are always UTC.
- Ledger writes and all OFX timestamps must be UTC.
- All COA/ledger metadata fields for created/updated times are UTC.
- Internal code must standardize to UTC for all decisions, logs, and DB writes.
- **Do not use any local/server time logic in trading or reporting.**
- `utils_time.py` must implement and export a canonical `utc_now()`:

```python
from datetime import datetime, timezone

def utc_now():
    return datetime.utcnow().replace(tzinfo=timezone.utc)
