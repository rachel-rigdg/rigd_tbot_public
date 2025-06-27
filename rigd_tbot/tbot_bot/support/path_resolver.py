# tbot_bot/support/path_resolver.py
# Resolves dynamic paths for TradeBot modules based on identity and file category.
# v041: Contains only runtime path logic for web UI or bot—never triggers any provisioning, bootstrapping, or privileged init.

import os
import re
from pathlib import Path
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
    "screeners": "screeners"
}

def get_bot_identity(explicit_identity: str = None) -> str:
    if 'is_first_bootstrap' in globals() and callable(is_first_bootstrap) and is_first_bootstrap():
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available (system is in bootstrap mode)")
    identity = explicit_identity if explicit_identity else load_bot_identity(default=None)
    if not identity or not get_bot_identity_string_regex().match(identity):
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    return identity


def validate_bot_identity(bot_identity: str) -> None:
    if not bot_identity or not re.match(IDENTITY_PATTERN, bot_identity):
        raise ValueError(f"[path_resolver] Invalid BOT_IDENTITY_STRING: {bot_identity}")

def get_bot_identity_string_regex():
    return re.compile(IDENTITY_PATTERN)

def get_output_path(bot_identity: str = None, category: str = None, filename: str = None, output_subdir: bool = False) -> str:
    identity = get_bot_identity(bot_identity)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    validate_bot_identity(identity)
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output" / identity
    if category not in CATEGORIES:
        raise ValueError(f"[path_resolver] Invalid output category: {category}")
    subdir = base_output_dir / CATEGORIES[category]
    subdir.mkdir(parents=True, exist_ok=True)
    if output_subdir:
        return str(subdir)
    return str(subdir / filename) if filename else str(subdir)

def resolve_category_path(category: str, filename: str = None, bot_identity: str = None, output_subdir: bool = False) -> str:
    return get_output_path(bot_identity=bot_identity, category=category, filename=filename, output_subdir=output_subdir)

def file_exists_resolved(bot_identity: str = None, category: str = None, filename: str = None) -> bool:
    try:
        path = get_output_path(bot_identity, category, filename)
        return os.path.exists(path)
    except Exception:
        return False

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

def resolve_coa_json_path() -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_coa_template.json")

def resolve_coa_metadata_path() -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_coa_metadata.json")

def resolve_coa_audit_log_path() -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_coa_audit.log")

def resolve_coa_json_path(bot_identity: str = None) -> str:
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

def resolve_output_folder_path(bot_identity: str) -> str:
    validate_bot_identity(bot_identity)
    return str(PROJECT_ROOT / "tbot_bot" / "output" / bot_identity)

def resolve_ledger_db_path(entity: str, jurisdiction: str, broker: str, bot_id: str) -> str:
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    validate_bot_identity(bot_identity)
    return str(Path(resolve_output_folder_path(bot_identity)) / "ledgers" / f"{bot_identity}_BOT_ledger.db")

def resolve_coa_db_path(entity: str, jurisdiction: str, broker: str, bot_id: str) -> str:
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    validate_bot_identity(bot_identity)
    return str(Path(resolve_output_folder_path(bot_identity)) / "ledgers" / f"{bot_identity}_BOT_COA_v1.0.0.db")

def resolve_universe_cache_path(bot_identity: str = None) -> str:
    """
    Returns full path to the symbol universe cache JSON file.
    Path: tbot_bot/output/screeners/symbol_universe.json
    """
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    screeners_dir = base_output_dir / "screeners"
    screeners_dir.mkdir(parents=True, exist_ok=True)
    return str(screeners_dir / "symbol_universe.json")

def resolve_status_log_path(bot_identity: str = None) -> str:
    """
    Returns the canonical path for the logs/status.json file.
    Path: tbot_bot/output/logs/status.json
    """
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output"
    logs_dir = base_output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return str(logs_dir / "status.json")

def resolve_status_summary_path(bot_identity: str = None) -> str:
    """
    Returns the canonical path for the summaries/status.json file.
    Path: tbot_bot/output/{bot_identity}/summaries/status.json
    """
    identity = get_bot_identity(bot_identity)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available or invalid (not yet configured)")
    validate_bot_identity(identity)
    summaries_dir = PROJECT_ROOT / "tbot_bot" / "output" / identity / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    return str(summaries_dir / "status.json")

def resolve_runtime_script_path(script_name: str) -> str:
    return str(PROJECT_ROOT / "tbot_bot" / "runtime" / script_name)

__all__ = [
    "get_bot_identity",
    "validate_bot_identity",
    "get_bot_identity_string_regex",
    "get_output_path",
    "resolve_category_path",
    "file_exists_resolved",
    "get_secret_path",
    "get_schema_path",
    "get_cache_path",
    "get_bot_state_path",
    "resolve_output_folder_path",
    "resolve_ledger_db_path",
    "resolve_coa_db_path",
    "resolve_coa_json_path",
    "resolve_coa_template_path",
    "resolve_coa_metadata_path",
    "resolve_coa_audit_log_path",
    "resolve_ledger_schema_path",
    "resolve_coa_schema_path",
    "resolve_universe_cache_path",
    "resolve_status_log_path",
    "resolve_status_summary_path",
    "resolve_runtime_script_path"
]
