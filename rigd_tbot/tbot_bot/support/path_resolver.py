# tbot_bot/support/path_resolver.py
# Resolves dynamic paths for TradeBot modules based on identity and file category.
# Fully supports staged universe/blocklist build, archival, and validation/diff ops per specification.
# All ledger, reporting, and COA outputs are aligned to compliance and accounting spec.

import os
import re
from pathlib import Path
from datetime import datetime
from tbot_bot.support.decrypt_secrets import load_bot_identity

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

def get_output_path(category: str = None, filename: str = None, bot_identity: str = None, output_subdir: bool = False) -> str:
    # Always allow system/bootstrap logs to resolve even in bootstrap mode.
    if category == "logs" and (filename in SYSTEM_LOG_FILES + BOOTSTRAP_ONLY_LOGS or filename == "test_mode.log"):
        logs_dir = PROJECT_ROOT / "tbot_bot" / "output" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return str(logs_dir / filename) if filename else str(logs_dir)
    # During bootstrap or if identity not available, use generic logs path
    identity = get_bot_identity(bot_identity)
    if not identity:
        # Generic non-identity logs path for early bootstrap, until config is saved
        if category == "logs":
            logs_dir = PROJECT_ROOT / "tbot_bot" / "output" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            return str(logs_dir / filename) if filename else str(logs_dir)
        else:
            # Fallback to generic output for non-logs categories
            generic_dir = PROJECT_ROOT / "tbot_bot" / "output" / (CATEGORIES.get(category, category or "logs"))
            generic_dir.mkdir(parents=True, exist_ok=True)
            return str(generic_dir / filename) if filename else str(generic_dir)
    validate_bot_identity(identity)
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output" / identity
    if category not in CATEGORIES:
        raise ValueError(f"[path_resolver] Invalid output category: {category}")
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
    snapshot_dir = PROJECT_ROOT / "tbot_bot" / "output" / bot_identity / "ledgers" / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    return str(snapshot_dir)

def resolve_control_path() -> Path:
    return PROJECT_ROOT / "tbot_bot" / "control"

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
    return str(PROJECT_ROOT / "tbot_bot" / "output" / identity / "ledgers" / "coa.json")

def resolve_coa_metadata_path(bot_identity: str = None) -> str:
    identity = get_bot_identity(bot_identity)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    validate_bot_identity(identity)
    return str(PROJECT_ROOT / "tbot_bot" / "output" / identity / "ledgers" / "coa_metadata.json")

def resolve_coa_audit_log_path(bot_identity: str = None) -> str:
    identity = get_bot_identity(bot_identity)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    validate_bot_identity(identity)
    return str(PROJECT_ROOT / "tbot_bot" / "output" / identity / "ledgers" / "coa_audit_log.json")

def resolve_coa_mapping_json_path(entity: str, jurisdiction: str, broker: str, bot_id: str) -> Path:
    """
    Returns the absolute Path to the COA mapping table JSON for this bot identity.
    Used by:
      - coa_mapping_table (load/save/upsert/version)
      - mapping_auto_update (inline edit → rule upsert)
    """
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    validate_bot_identity(bot_identity)
    mapping_dir = PROJECT_ROOT / "tbot_bot" / "output" / bot_identity / "ledgers"
    mapping_dir.mkdir(parents=True, exist_ok=True)
    return mapping_dir / "coa_mapping_table.json"

def resolve_output_folder_path(bot_identity: str) -> str:
    validate_bot_identity(bot_identity)
    return str(PROJECT_ROOT / "tbot_bot" / "output" / bot_identity)

def resolve_output_path(rel_path):
    """
    Returns absolute path for any output file, creating parent directories as needed.
    All logs/output go to tbot_bot/output/.
    """
    root = Path(__file__).resolve().parents[2]
    out_path = root / "tbot_bot" / "output" / rel_path
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
    return str(Path(resolve_output_folder_path(bot_identity)) / "ledgers" / f"{bot_identity}_BOT_ledger.db")

def resolve_coa_db_path(entity: str, jurisdiction: str, broker: str, bot_id: str) -> str:
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    validate_bot_identity(bot_identity)
    return str(PROJECT_ROOT / "tbot_bot" / "output" / bot_identity / "ledgers" / f"{bot_identity}_BOT_COA.db")

def resolve_universe_cache_path(bot_identity: str = None) -> str:
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    screeners_dir = base_output_dir / "screeners"
    screeners_dir.mkdir(parents=True, exist_ok=True)
    return str(screeners_dir / "symbol_universe.json")

def resolve_universe_raw_path():
    return os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', 'output', 'screeners', 'symbol_universe.symbols_raw.json'
    ))

def resolve_universe_unfiltered_path() -> str:
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    screeners_dir = base_output_dir / "screeners"
    screeners_dir.mkdir(parents=True, exist_ok=True)
    return str(screeners_dir / "symbol_universe.unfiltered.json")

def resolve_universe_partial_path() -> str:
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    screeners_dir = base_output_dir / "screeners"
    screeners_dir.mkdir(parents=True, exist_ok=True)
    return str(screeners_dir / "symbol_universe.partial.json")

def resolve_universe_log_path() -> str:
    # === Reporting logger refactor: reporting/universe_logger.py ===
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    screeners_dir = base_output_dir / "screeners"
    screeners_dir.mkdir(parents=True, exist_ok=True)
    return str(screeners_dir / "universe_ops.log")

def resolve_universe_logger_path() -> str:
    # Path for reporting/universe_logger.py (for backward compatibility)
    return str(PROJECT_ROOT / "tbot_bot" / "reporting" / "universe_logger.py")

def resolve_screener_blocklist_path() -> str:
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    screeners_dir = base_output_dir / "screeners"
    screeners_dir.mkdir(parents=True, exist_ok=True)
    return str(screeners_dir / "screener_blocklist.txt")

def resolve_blocklist_archive_path(archive_date: str = None) -> str:
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    screeners_dir = base_output_dir / "screeners"
    screeners_dir.mkdir(parents=True, exist_ok=True)
    if not archive_date:
        archive_date = datetime.utcnow().strftime("%Y%m%d")
    return str(screeners_dir / f"blocklist_archive_{archive_date}.txt")

def resolve_universe_archive_path(archive_date: str = None) -> str:
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    screeners_dir = base_output_dir / "screeners"
    screeners_dir.mkdir(parents=True, exist_ok=True)
    if not archive_date:
        archive_date = datetime.utcnow().strftime("%Y%m%d")
    return str(screeners_dir / f"symbol_universe_{archive_date}.json")

def resolve_status_log_path(bot_identity: str = None) -> str:
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    logs_dir = base_output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return str(logs_dir / "status.json")

def resolve_status_summary_path(bot_identity: str = None) -> str:
    identity = get_bot_identity(bot_identity)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    validate_bot_identity(identity)
    summaries_dir = PROJECT_ROOT / "tbot_bot" / "output" / identity / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    return str(summaries_dir / "status.json")

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
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    screeners_dir = base_output_dir / "screeners"
    screeners_dir.mkdir(parents=True, exist_ok=True)
    return str(screeners_dir / "nasdaqlisted.txt")

def resolve_holdings_audit_log_path(bot_identity: str = None) -> str:
    identity = get_bot_identity(bot_identity)
    validate_bot_identity(identity)
    return str(PROJECT_ROOT / "tbot_bot" / "output" / identity / "logs" / "holdings_audit.log")

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
    .../output/{BOT_IDENTITY}/logs/schedule.json
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

__all__ = [
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
