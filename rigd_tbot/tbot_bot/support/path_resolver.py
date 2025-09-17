# tbot_bot/support/path_resolver.py
# Resolves dynamic paths for TradeBot modules based on identity and file category.
# Fully supports staged universe/blocklist build, archival, and validation/diff ops per specification.
# All ledger, reporting, and COA outputs are aligned to compliance and accounting spec.
# TEST-MODE AWARE: When TEST_MODE flag exists, ALL writes are redirected under output/_test/...
#                  This keeps test artifacts isolated from live logs/ledgers/trades.

import os
import re
from pathlib import Path
from datetime import datetime
from tbot_bot.support.decrypt_secrets import load_bot_identity
from __future__ import annotations


try:
    from tbot_bot.support.bootstrap_utils import is_first_bootstrap
except ImportError:
    def is_first_bootstrap():
        return False

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IDENTITY_PATTERN = r"^[A-Z]{2,6}_[A-Z]{2,4}_[A-Z]{2,10}_[A-Z0-9]{2,6}$"

CATEGORIES = {
    "logs": "logs",
    "ledgers": "ledgers",
    "summaries": "summaries",
    "trades": "trades",
    "screeners": "screeners",
    "enhancements": "enhancements",
    "locks": "locks",  # NEW: for per-day/per-task lockfiles
}

SYSTEM_LOG_FILES = [
    "main_bot.log",
    "system_logs.log",
    "heartbeat.log",
    "router.log",
    "screener.log",
    "kill_switch.log",
    "provisioning.log",
    "provisioning_status.json",
    "auth_web.log",
    "security_users.log",
    "system_users.log",
    "user_activity_monitoring.log",
    "start_log",
    "stop_log",
    "password_reset_tokens.log"
]

BOOTSTRAP_ONLY_LOGS = [
    "init_system_logs.log",
    "init_system_users.log",
    "init_user_activity_monitoring.log",
    "init_password_reset_tokens.log"
]

# --- TEST-MODE detection (flag file) ---
_CONTROL_DIR = PROJECT_ROOT / "tbot_bot" / "control"
_TEST_MODE_FLAG = _CONTROL_DIR / "test_mode.flag"

def is_test_mode_active() -> bool:
    """Return True if TEST_MODE flag file exists."""
    try:
        return _TEST_MODE_FLAG.exists()
    except Exception:
        return False

# --- Identity helpers ---
def get_bot_identity(explicit_identity: str = None) -> str:
    """
    Returns a validated BOT_IDENTITY_STRING or None during first bootstrap.
    """
    if is_first_bootstrap():
        return explicit_identity if explicit_identity else None
    identity = explicit_identity if explicit_identity else load_bot_identity()
    if not identity or not get_bot_identity_string_regex().match(identity):
        return None
    return identity

def validate_bot_identity(bot_identity: str) -> None:
    if not bot_identity or not re.match(IDENTITY_PATTERN, bot_identity):
        raise ValueError(f"[path_resolver] Invalid BOT_IDENTITY_STRING: {bot_identity}")

def get_bot_identity_string_regex():
    return re.compile(IDENTITY_PATTERN)

# --- Base output root (TEST-MODE aware) ---
def _base_output_root(identity: str | None) -> Path:
    """
    Returns the base output directory:
      - Live:  .../output/{IDENTITY}  (or generic .../output when identity is None for bootstrap/generic categories)
      - Test:  .../output/_test/{IDENTITY or 'generic'}
    """
    output_root = PROJECT_ROOT / "tbot_bot" / "output"
    if is_test_mode_active():
        test_bucket = output_root / "_test" / (identity if identity else "generic")
        test_bucket.mkdir(parents=True, exist_ok=True)
        return test_bucket
    # live paths
    if identity:
        live_bucket = output_root / identity
        live_bucket.mkdir(parents=True, exist_ok=True)
        return live_bucket
    # generic (no identity yet)
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root

def get_output_path(category: str = None, filename: str = None, bot_identity: str = None, output_subdir: bool = False) -> str:
    # Always allow system/bootstrap logs to resolve even in bootstrap mode.
    if category == "logs" and (filename in SYSTEM_LOG_FILES + BOOTSTRAP_ONLY_LOGS or filename == "test_mode.log"):
        logs_dir = _base_output_root(None) / "logs" if is_test_mode_active() else (PROJECT_ROOT / "tbot_bot" / "output" / "logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        return str(logs_dir / filename) if filename else str(logs_dir)

    # During bootstrap or if identity not available, use generic path roots
    identity = get_bot_identity(bot_identity)
    if not identity:
        # Generic non-identity logs path for early bootstrap, until config is saved
        if category == "logs":
            logs_dir = _base_output_root(None) / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            return str(logs_dir / filename) if filename else str(logs_dir)
        else:
            # Fallback to generic output for non-logs categories
            generic_dir = _base_output_root(None) / (CATEGORIES.get(category, category or "logs"))
            generic_dir.mkdir(parents=True, exist_ok=True)
            return str(generic_dir / filename) if filename else str(generic_dir)

    # Identity present
    validate_bot_identity(identity)
    if category not in CATEGORIES:
        raise ValueError(f"[path_resolver] Invalid output category: {category}")
    base_output_dir = _base_output_root(identity)
    subdir = base_output_dir / CATEGORIES[category]
    subdir.mkdir(parents=True, exist_ok=True)
    if output_subdir:
        return str(subdir)
    return str(subdir / filename) if filename else str(subdir)

def resolve_ledger_snapshot_dir(entity: str, jurisdiction: str, broker: str, bot_id: str) -> str:
    """
    Directory where pre/post sync snapshots are stored.
    Used by: ledger_snapshot, runtime sync wrapper.
    """
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    validate_bot_identity(bot_identity)
    snapshots_dir = Path(get_output_path(category="ledgers", bot_identity=bot_identity, output_subdir=True)) / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    return str(snapshots_dir)

def resolve_control_path() -> Path:
    return _CONTROL_DIR

def resolve_category_path(category: str, filename: str = None, bot_identity: str = None, output_subdir: bool = False) -> str:
    return get_output_path(category=category, filename=filename, bot_identity=bot_identity, output_subdir=output_subdir)

def file_exists_resolved(bot_identity: str = None, category: str = None, filename: str = None) -> bool:
    try:
        path = get_output_path(category=category, filename=filename, bot_identity=bot_identity)
        return os.path.exists(path)
    except Exception:
        return False

def get_project_root() -> Path:
    return PROJECT_ROOT

def get_secret_path(filename: str) -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "storage" / "secrets" / filename)

def get_schema_path(filename: str) -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "core" / "schemas" / filename)

def get_cache_path(filename: str) -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "data" / "cache" / filename)

def get_bot_state_path() -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "control" / "bot_state.txt")

def resolve_coa_template_path() -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_coa_template.json")

def resolve_ledger_schema_path():
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_schema.sql")

def resolve_coa_schema_path():
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "coa_schema.sql")

def resolve_coa_json_path(bot_identity: str = None) -> str:
    """
    Path to the active COA JSON used by:
      - utils_coa_web.load_coa_metadata_and_accounts
      - ledger_opening_balance (account resolution)
    """
    identity = get_bot_identity(bot_identity)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    validate_bot_identity(identity)
    return get_output_path(category="ledgers", filename="coa.json", bot_identity=identity)

def resolve_coa_metadata_path(bot_identity: str = None) -> str:
    identity = get_bot_identity(bot_identity)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    validate_bot_identity(identity)
    return get_output_path(category="ledgers", filename="coa_metadata.json", bot_identity=identity)

def resolve_coa_audit_log_path(bot_identity: str = None) -> str:
    identity = get_bot_identity(bot_identity)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    validate_bot_identity(identity)
    return get_output_path(category="ledgers", filename="coa_audit_log.json", bot_identity=identity)

def resolve_coa_mapping_json_path(entity: str, jurisdiction: str, broker: str, bot_id: str) -> Path:
    """
    Returns the absolute Path to the COA mapping table JSON for this bot identity.
    Used by:
      - coa_mapping_table (load/save/upsert/version)
      - mapping_auto_update (inline edit → rule upsert)
    """
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    validate_bot_identity(bot_identity)
    mapping_dir = Path(get_output_path(category="ledgers", bot_identity=bot_identity, output_subdir=True))
    mapping_dir.mkdir(parents=True, exist_ok=True)
    return mapping_dir / "coa_mapping_table.json"

def resolve_output_folder_path(bot_identity: str) -> str:
    validate_bot_identity(bot_identity)
    return str(_base_output_root(bot_identity))

def resolve_output_path(rel_path):
    """
    Returns absolute path for any output file, creating parent directories as needed.
    TEST-MODE aware: prefixes with output/_test when active.
    """
    # Normalize to Path
    rel_path = Path(rel_path)
    if is_test_mode_active():
        out_path = PROJECT_ROOT / "tbot_bot" / "output" / "_test" / "generic" / rel_path
    else:
        out_path = PROJECT_ROOT / "tbot_bot" / "output" / rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return str(out_path)

def resolve_ledger_db_path(entity: str, jurisdiction: str, broker: str, bot_id: str) -> str:
    """
    SQLite ledger DB used by:
      - ledger_balance (balances/rollups)
      - ledger_edit (audited account reassignment)
      - ledger_opening_balance (OB batch)
    """
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    validate_bot_identity(bot_identity)
    return str(Path(get_output_path(category="ledgers", bot_identity=bot_identity, output_subdir=True)) / f"{bot_identity}_BOT_ledger.db")

def resolve_coa_db_path(entity: str, jurisdiction: str, broker: str, bot_id: str) -> str:
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    validate_bot_identity(bot_identity)
    return str(Path(get_output_path(category="ledgers", bot_identity=bot_identity, output_subdir=True)) / f"{bot_identity}_BOT_COA.db")

def resolve_universe_cache_path(bot_identity: str = None) -> str:
    return get_output_path(category="screeners", filename="symbol_universe.json", bot_identity=bot_identity)

def resolve_universe_raw_path():
    # legacy raw dump path; keep under screeners category
    return get_output_path(category="screeners", filename="symbol_universe.symbols_raw.json", bot_identity=None)

def resolve_universe_unfiltered_path() -> str:
    return get_output_path(category="screeners", filename="symbol_universe.unfiltered.json", bot_identity=None)

def resolve_universe_partial_path() -> str:
    return get_output_path(category="screeners", filename="symbol_universe.partial.json", bot_identity=None)

def resolve_universe_log_path() -> str:
    # === Reporting logger refactor: reporting/universe_logger.py ===
    return get_output_path(category="screeners", filename="universe_ops.log", bot_identity=None)

def resolve_universe_logger_path() -> str:
    # Path for reporting/universe_logger.py (for backward compatibility)
    return str(PROJECT_ROOT / "tbot_bot" / "reporting" / "universe_logger.py")

def resolve_screener_blocklist_path() -> str:
    return get_output_path(category="screeners", filename="screener_blocklist.txt", bot_identity=None)

def resolve_blocklist_archive_path(archive_date: str = None) -> str:
    if not archive_date:
        archive_date = datetime.utcnow().strftime("%Y%m%d")
    return get_output_path(category="screeners", filename=f"blocklist_archive_{archive_date}.txt", bot_identity=None)

def resolve_universe_archive_path(archive_date: str = None) -> str:
    if not archive_date:
        archive_date = datetime.utcnow().strftime("%Y%m%d")
    return get_output_path(category="screeners", filename=f"symbol_universe_{archive_date}.json", bot_identity=None)

def resolve_status_log_path(bot_identity: str = None) -> str:
    return get_output_path(category="logs", filename="status.json", bot_identity=bot_identity)

def resolve_status_summary_path(bot_identity: str = None) -> str:
    identity = get_bot_identity(bot_identity)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    validate_bot_identity(identity)
    return get_output_path(category="summaries", filename="status.json", bot_identity=identity)

def resolve_runtime_script_path(script_name: str) -> str:
    if script_name == "universe_orchestrator.py":
        return str(PROJECT_ROOT / "tbot_bot" / "screeners" / "universe_orchestrator.py")
    return str(PROJECT_ROOT / "tbot_bot" / "runtime" / script_name)

def resolve_support_script_path(script_name: str) -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "support" / script_name)

def resolve_test_script_path(script_name: str) -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "test" / script_name)

def resolve_status_bot_path() -> str:
    return resolve_runtime_script_path("status_bot.py")

def resolve_watchdog_bot_path() -> str:
    return resolve_runtime_script_path("watchdog_bot.py")

def resolve_strategy_router_path() -> str:
    return resolve_runtime_script_path("strategy_router.py")

def resolve_strategy_open_path() -> str:
    return resolve_runtime_script_path("strategy_open.py")

def resolve_strategy_mid_path() -> str:
    return resolve_runtime_script_path("strategy_mid.py")

def resolve_strategy_close_path() -> str:
    return resolve_runtime_script_path("strategy_close.py")

def resolve_risk_module_path() -> str:
    return resolve_runtime_script_path("risk_module.py")

def resolve_kill_switch_path() -> str:
    return resolve_runtime_script_path("kill_switch.py")

def resolve_log_rotation_path() -> str:
    return resolve_runtime_script_path("log_rotation.py")

def resolve_trade_logger_path() -> str:
    return resolve_runtime_script_path("trade_logger.py")

def resolve_status_logger_path() -> str:
    return resolve_runtime_script_path("status_logger.py")

def resolve_symbol_universe_refresh_path() -> str:
    """
    Path to the symbol_universe_refresh runtime (for screeners refresh jobs).
    """
    return str(PROJECT_ROOT / "tbot_bot" / "runtime" / "symbol_universe_refresh.py")

def resolve_integration_test_runner_path() -> str:
    return resolve_test_script_path("integration_test_runner.py")

def resolve_nasdaqlisted_txt_path() -> str:
    return get_output_path(category="screeners", filename="nasdaqlisted.txt", bot_identity=None)

def resolve_holdings_audit_log_path(bot_identity: str = None) -> str:
    identity = get_bot_identity(bot_identity)
    validate_bot_identity(identity)
    return get_output_path(category="logs", filename="holdings_audit.log", bot_identity=identity)

# --- Holdings Management Paths (NEW) ---

def resolve_holdings_secrets_path() -> Path:
    """Returns path to holdings_secrets.json.enc (encrypted holdings config)."""
    return PROJECT_ROOT / "tbot_bot" / "storage" / "secrets" / "holdings_secrets.json.enc"

def resolve_holdings_secrets_key_path() -> Path:
    """Returns path to Fernet key for holdings secrets."""
    return PROJECT_ROOT / "tbot_bot" / "storage" / "keys" / "holdings_secrets.key"

def resolve_holdings_secrets_backup_dir() -> Path:
    """Returns path to the holdings secrets backup directory."""
    backup_dir = PROJECT_ROOT / "tbot_bot" / "storage" / "backups" / "holdings_secrets"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir

# ----------------------------------------------------------------------
# NEW HELPERS (scoped to {BOT_IDENTITY}) for supervisor, logs, and lockfiles
# ----------------------------------------------------------------------

def get_schedule_json_path(bot_identity: str = None) -> str:
    """
    .../output/{BOT_IDENTITY or _test/generic}/logs/schedule.json
    Falls back to generic output/logs if identity is not yet available (bootstrap).
    """
    return get_output_path(category="logs", filename="schedule.json", bot_identity=bot_identity)

def get_supervisor_lock_path(trading_date: str, bot_identity: str = None) -> str:
    """
    .../output/{BOT_IDENTITY}/locks/supervisor_<date>.lock
    """
    fname = f"supervisor_{trading_date}.lock"
    return get_output_path(category="locks", filename=fname, bot_identity=bot_identity)

def get_holdings_lock_path(trading_date: str, bot_identity: str = None) -> str:
    """
    .../output/{BOT_IDENTITY}/locks/holdings_<date>.lock
    """
    fname = f"holdings_{trading_date}.lock"
    return get_output_path(category="locks", filename=fname, bot_identity=bot_identity)

def get_phase_log_path(phase: str, bot_identity: str = None) -> str:
    """
    .../output/{BOT_IDENTITY}/logs/{phase}.log
    """
    fname = f"{phase}.log"
    return get_output_path(category="logs", filename=fname, bot_identity=bot_identity)

# --- Enhancements path helper (referenced in __all__) ---
def get_enhancements_path(bot_identity: str = None, output_subdir: bool = True) -> str:
    """
    Returns the enhancements output directory (TEST-MODE aware).
    """
    return get_output_path(category="enhancements", bot_identity=bot_identity, output_subdir=output_subdir)

__all__ = [
    "is_test_mode_active",
    "get_bot_identity",
    "validate_bot_identity",
    "get_bot_identity_string_regex",
    "get_output_path",
    "resolve_control_path",
    "resolve_category_path",
    "file_exists_resolved",
    "get_secret_path",
    "get_schema_path",
    "get_cache_path",
    "get_bot_state_path",
    "get_enhancements_path",
    "resolve_output_folder_path",
    "resolve_ledger_db_path",
    "resolve_ledger_snapshot_dir",
    "resolve_coa_db_path",
    "resolve_coa_json_path",
    "resolve_coa_template_path",
    "resolve_coa_metadata_path",
    "resolve_coa_audit_log_path",
    "resolve_coa_mapping_json_path",
    "resolve_ledger_schema_path",
    "resolve_coa_schema_path",
    "resolve_universe_cache_path",
    "resolve_universe_raw_path",
    "resolve_universe_unfiltered_path",
    "resolve_universe_partial_path",
    "resolve_universe_log_path",
    "resolve_universe_logger_path",
    "resolve_screener_blocklist_path",
    "resolve_blocklist_archive_path",
    "resolve_universe_archive_path",
    "resolve_status_log_path",
    "resolve_status_summary_path",
    "resolve_runtime_script_path",
    "resolve_support_script_path",
    "resolve_test_script_path",
    "resolve_status_bot_path",
    "resolve_watchdog_bot_path",
    "resolve_strategy_router_path",
    "resolve_strategy_open_path",
    "resolve_strategy_mid_path",
    "resolve_strategy_close_path",
    "resolve_risk_module_path",
    "resolve_kill_switch_path",
    "resolve_log_rotation_path",
    "resolve_trade_logger_path",
    "resolve_status_logger_path",
    "resolve_symbol_universe_refresh_path",
    "resolve_integration_test_runner_path",
    "resolve_nasdaqlisted_txt_path",
    "get_project_root",
    "resolve_holdings_audit_log_path",
    "resolve_holdings_secrets_path",
    "resolve_holdings_secrets_key_path",
    "resolve_holdings_secrets_backup_dir",
    # NEW:
    "get_schedule_json_path",
    "get_supervisor_lock_path",
    "get_holdings_lock_path",
    "get_phase_log_path",
]
