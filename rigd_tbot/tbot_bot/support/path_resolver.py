# tbot_bot/support/path_resolver.py
# Resolves dynamic paths for TradeBot modules based on identity and file category.
# v041: Contains only runtime path logic for web UI or bot—never triggers any provisioning, bootstrapping, or privileged init.

import os
import re
from pathlib import Path
from tbot_bot.support.decrypt_secrets import load_bot_identity

# Optional: Import is_first_bootstrap for guarding functions if called before config exists
try:
    from tbot_web.py.bootstrap_utils import is_first_bootstrap
except ImportError:
    is_first_bootstrap = lambda: False  # fallback for non-web contexts

# Define project root for absolute path resolution
PROJECT_ROOT = Path(__file__).resolve().parents[2]

IDENTITY_PATTERN = r"^[A-Z]{2,6}_[A-Z]{2,4}_[A-Z]{2,10}_[0-9]{2,4}$"

CATEGORIES = {
    "logs": "logs",
    "ledgers": "ledgers",
    "summaries": "summaries",
    "trades": "trades"
}

def get_bot_identity(explicit_identity: str = None) -> str:
    """
    Returns the BOT_IDENTITY_STRING (explicit or decrypted from secrets), or raises cleanly if absent.
    Never performs any provisioning/bootstrapping logic.
    """
    # Guard: If in bootstrap mode, do not attempt to resolve identity
    if 'is_first_bootstrap' in globals() and callable(is_first_bootstrap) and is_first_bootstrap():
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available (system is in bootstrap mode)")
    identity = explicit_identity if explicit_identity else load_bot_identity(default=None)
    if not identity:
        raise RuntimeError("[path_resolver] BOT_IDENTITY_STRING not available (not yet configured)")
    return identity

def validate_bot_identity(bot_identity: str) -> None:
    if not re.match(IDENTITY_PATTERN, bot_identity):
        raise ValueError(f"[path_resolver] Invalid BOT_IDENTITY_STRING: {bot_identity}")

def get_output_path(bot_identity: str = None, category: str = None, filename: str = None, output_subdir: bool = False) -> str:
    """
    Returns the full output path for a given file category under the specified bot identity.
    Returns absolute paths relative to project root.
    """
    identity = get_bot_identity(bot_identity)
    validate_bot_identity(identity)
    base_output_dir = PROJECT_ROOT / "tbot_bot" / "output" / identity
    if category not in CATEGORIES:
        raise ValueError(f"[path_resolver] Invalid output category: {category}")
    subdir = base_output_dir / CATEGORIES[category]
    if output_subdir:
        subdir.mkdir(parents=True, exist_ok=True)
        return str(subdir)
    else:
        subdir.mkdir(parents=True, exist_ok=True)
        return str(subdir / filename) if filename else str(subdir)

def resolve_category_path(category: str, filename: str = None, bot_identity: str = None, output_subdir: bool = False) -> str:
    """
    Returns the resolved output path for the given category, mirroring get_output_path but with a simpler API for web UI.
    """
    return get_output_path(bot_identity=bot_identity, category=category, filename=filename, output_subdir=output_subdir)

def file_exists_resolved(bot_identity: str = None, category: str = None, filename: str = None) -> bool:
    """
    Checks if the resolved output file exists.
    """
    try:
        path = get_output_path(bot_identity, category, filename)
        return os.path.exists(path)
    except Exception:
        return False

def get_secret_path(filename: str) -> str:
    """
    Returns the absolute path to an encrypted secret file in /storage/secrets/
    """
    return str(PROJECT_ROOT / "tbot_bot" / "storage" / "secrets" / filename)

def get_schema_path(filename: str) -> str:
    """
    Returns the absolute path to a schema file in /core/schemas/
    """
    return str(PROJECT_ROOT / "tbot_bot" / "core" / "schemas" / filename)

def get_cache_path(filename: str) -> str:
    """
    Returns the absolute path to a runtime cache file in /data/cache/
    """
    return str(PROJECT_ROOT / "tbot_bot" / "data" / "cache" / filename)

# === COA support: JSON, metadata, and audit log resolution ===

def resolve_coa_json_path() -> str:
    """
    Resolves absolute path to tbot_bot/accounting/tbot_ledger_coa.json
    """
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_coa.json")

def resolve_coa_template_path() -> str:
    """
    Resolves absolute path to tbot_bot/accounting/tbot_ledger_coa.json
    """
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_coa.json")

def resolve_coa_metadata_path() -> str:
    """
    Resolves absolute path to tbot_bot/accounting/tbot_ledger_coa_metadata.json
    """
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_coa_metadata.json")

def resolve_coa_audit_log_path() -> str:
    """
    Resolves absolute path to tbot_bot/accounting/tbot_ledger_coa_audit.log
    """
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_coa_audit.log")

def resolve_ledger_schema_path():
    """
    Returns the absolute path to the ledger schema file in /accounting/tbot_ledger_schema.sql
    """
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "tbot_ledger_schema.sql")

def resolve_coa_schema_path():
    """
    Returns the absolute path to the COA schema file in /accounting/coa_schema.sql
    """
    return str(PROJECT_ROOT / "tbot_bot" / "accounting" / "coa_schema.sql")

def resolve_output_folder_path(bot_identity: str) -> str:
    """
    Returns the absolute path to the bot-specific output folder.
    """
    validate_bot_identity(bot_identity)
    return str(PROJECT_ROOT / "tbot_bot" / "output" / bot_identity)

def resolve_ledger_db_path(entity: str, jurisdiction: str, broker: str, bot_id: str) -> str:
    """
    Returns the absolute path to the ledger DB for the specified bot.
    """
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    return str(Path(resolve_output_folder_path(bot_identity)) / "ledgers" / f"{bot_identity}_BOT_ledger.db")

def resolve_coa_db_path(entity: str, jurisdiction: str, broker: str, bot_id: str) -> str:
    """
    Returns the absolute path to the COA DB for the specified bot.
    """
    bot_identity = f"{entity}_{jurisdiction}_{broker}_{bot_id}"
    return str(Path(resolve_output_folder_path(bot_identity)) / "ledgers" / f"{bot_identity}_BOT_COA_v1.0.0.db")

__all__ = [
    "get_bot_identity",
    "validate_bot_identity",
    "get_output_path",
    "resolve_category_path",
    "file_exists_resolved",
    "get_secret_path",
    "get_schema_path",
    "get_cache_path",
    "resolve_output_folder_path",
    "resolve_ledger_db_path",
    "resolve_coa_db_path",
    "resolve_coa_json_path",
    "resolve_coa_template_path",
    "resolve_coa_metadata_path",
    "resolve_coa_audit_log_path",
    "resolve_ledger_schema_path",
    "resolve_coa_schema_path"
]
