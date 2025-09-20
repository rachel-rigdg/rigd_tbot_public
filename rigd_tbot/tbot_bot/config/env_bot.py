# tbot_bot/config/env_bot.py
# summary: Validates and parses .env_bot configuration (encrypted only, never auto-loads at module level).
# All config access must be explicit and deferred—no module-level loading permitted.
# NOTE: Holdings-related variables have been moved to the holdings secrets file and are NOT loaded here.

import json
import logging
from cryptography.fernet import Fernet
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# PATH RESOLUTION (fix): robust lookup + env overrides + clear errors
# ----------------------------------------------------------------------

def _resolve_first_existing(candidates: List[Path]) -> Optional[Path]:
    for p in candidates:
        try:
            if p.exists():
                return p
        except Exception:
            # ignore permission/odd FS errors; try next
            pass
    return None

def _env_override_path(env_key: str) -> Optional[Path]:
    import os
    v = os.environ.get(env_key)
    if v:
        p = Path(v).expanduser().resolve()
        return p
    return None

# Base anchors
_THIS_FILE = Path(__file__).resolve()
_CONFIG_DIR = _THIS_FILE.parent              # .../tbot_bot/config
_TBOT_ROOT = _CONFIG_DIR.parent             # .../tbot_bot

# Candidate locations (in priority order, after env overrides)
_ENC_CANDIDATES = [
    _TBOT_ROOT / "support" / ".env_bot.enc",                 # original default
    _TBOT_ROOT / "storage" / "secrets" / ".env_bot.enc",     # alt layout seen in error
    _TBOT_ROOT / "storage" / ".env_bot.enc",                 # simple storage root
    _CONFIG_DIR / "support" / ".env_bot.enc",                # if someone nested under config
]

_KEY_CANDIDATES = [
    _TBOT_ROOT / "storage" / "keys" / "env_bot.key",         # original default
    _TBOT_ROOT / "support" / "env_bot.key",                  # alt under support
    _CONFIG_DIR / "support" / "env_bot.key",                 # if nested under config
]

def _resolve_encrypted_paths() -> (Path, Path, List[Path], List[Path]):
    """Return (enc_path, key_path, tried_enc, tried_key) with env overrides applied."""
    tried_enc: List[Path] = []
    tried_key: List[Path] = []

    enc_override = _env_override_path("TBOT_ENV_BOT_ENC_PATH")
    key_override = _env_override_path("TBOT_ENV_BOT_KEY_PATH")

    if enc_override:
        tried_enc.append(enc_override)
        enc_path = enc_override if enc_override.exists() else None
    else:
        tried_enc.extend(_ENC_CANDIDATES)
        enc_path = _resolve_first_existing(_ENC_CANDIDATES)

    if key_override:
        tried_key.append(key_override)
        key_path = key_override if key_override.exists() else None
    else:
        tried_key.extend(_KEY_CANDIDATES)
        key_path = _resolve_first_existing(_KEY_CANDIDATES)

    return enc_path, key_path, tried_enc, tried_key

# ----------------------------------------------------------------------
# REQUIRED KEYS (unchanged except prior note)
# ----------------------------------------------------------------------

REQUIRED_KEYS = [
    # General & Debugging
    "VERSION_TAG", "BUILD_MODE", "DISABLE_ALL_TRADES", "ENABLE_LOGGING", "LOG_FORMAT", "DEBUG_LOG_LEVEL",
    # Trade Execution & Risk Controls
    "TRADE_CONFIRMATION_REQUIRED", "API_RETRY_LIMIT", "API_TIMEOUT", "FRACTIONAL", "TOTAL_ALLOCATION",
    "MAX_TRADES", "CANDIDATE_MULTIPLIER", "WEIGHTS", "DAILY_LOSS_LIMIT", "MAX_RISK_PER_TRADE", "MAX_OPEN_POSITIONS",
    # Screeners Configuration
    "SCREENER_UNIVERSE_MAX_AGE_DAYS", "SCREENER_UNIVERSE_EXCHANGES", "SCREENER_UNIVERSE_MIN_PRICE",
    "SCREENER_UNIVERSE_MAX_PRICE", "SCREENER_UNIVERSE_MIN_MARKET_CAP", "SCREENER_UNIVERSE_MAX_MARKET_CAP",
    "SCREENER_UNIVERSE_MAX_SIZE", "SCREENER_UNIVERSE_BLOCKLIST_PATH", "SCREENER_TEST_MODE_UNIVERSE",
    # Price & Volume Filters
    "MIN_PRICE", "MAX_PRICE", "MIN_VOLUME_THRESHOLD", "ENABLE_FUNNHUB_FUNDAMENTALS_FILTER",
    "MAX_PE_RATIO", "MAX_DEBT_EQUITY",
    # Strategy Routing & Broker Mode
    "STRATEGY_SEQUENCE", "STRATEGY_OVERRIDE",
    # Automated Rebalance Triggers
    "ACCOUNT_BALANCE", "REBALANCE_ENABLED", "REBALANCE_THRESHOLD", "REBALANCE_CHECK_INTERVAL",
    # Failover Broker Routing
    "FAILOVER_ENABLED", "FAILOVER_LOG_TAG",
    # Global Time & Polling
    "MARKET_OPEN_UTC", "MARKET_CLOSE_UTC", "TRADING_DAYS",
    # NEW: Sleep times for universe and strategy API polling
    "UNIVERSE_SLEEP_TIME", "STRATEGY_SLEEP_TIME",
    # OPEN Strategy Configuration
    "STRAT_OPEN_ENABLED", "START_TIME_OPEN", "OPEN_ANALYSIS_TIME", "OPEN_BREAKOUT_TIME", "OPEN_MONITORING_TIME",
    "STRAT_OPEN_BUFFER", "SHORT_TYPE_OPEN", "MAX_GAP_PCT_OPEN", "MIN_MARKET_CAP_OPEN", "MAX_MARKET_CAP_OPEN",
    # MID Strategy Configuration
    "STRAT_MID_ENABLED", "START_TIME_MID", "MID_ANALYSIS_TIME", "MID_BREAKOUT_TIME", "MID_MONITORING_TIME",
    "STRAT_MID_VWAP_THRESHOLD", "SHORT_TYPE_MID", "MAX_GAP_PCT_MID", "MIN_MARKET_CAP_MID", "MAX_MARKET_CAP_MID",
    # CLOSE Strategy Configuration
    "STRAT_CLOSE_ENABLED", "START_TIME_CLOSE", "CLOSE_ANALYSIS_TIME", "CLOSE_BREAKOUT_TIME",
    "CLOSE_MONITORING_TIME", "STRAT_CLOSE_VIX_THRESHOLD", "SHORT_TYPE_CLOSE", "MAX_GAP_PCT_CLOSE",
    "MIN_MARKET_CAP_CLOSE", "MAX_MARKET_CAP_CLOSE",
    # Notifications
    "NOTIFY_ON_FILL", "NOTIFY_ON_EXIT",
    # Reporting & Ledger Export
    "LEDGER_EXPORT_MODE",
    # Defense Mode
    "DEFENSE_MODE_ACTIVE", "DEFENSE_MODE_TRADE_LIMIT_PCT", "DEFENSE_MODE_TOTAL_ALLOCATION",
    # ENHANCEMENT MODULE TOGGLES
    "ENABLE_REBALANCE_NOTIFIER", "REBALANCE_TRIGGER_PCT", "RBAC_ENABLED", "DEFAULT_USER_ROLE",
    "ENABLE_STRATEGY_OPTIMIZER", "OPTIMIZER_BACKTEST_LOOKBACK_DAYS", "OPTIMIZER_ALGORITHM", "OPTIMIZER_OUTPUT_DIR",
    "NOTIFY_ON_FAILURE", "CRITICAL_ALERT_CHANNEL", "ROUTINE_ALERT_CHANNEL",
    "ENABLE_SLIPPAGE_MODEL", "SLIPPAGE_SIMULATION_TYPE", "SLIPPAGE_MEAN_PCT", "SLIPPAGE_STDDEV_PCT", "SIMULATED_LATENCY_MS",
    "ENABLE_BSM_FILTER", "MAX_BSM_DEVIATION", "RISK_FREE_RATE", "RISK_FREE_RATE_SOURCE"
    # All holdings-related config has been removed from REQUIRED_KEYS
    # DO NOT REQUIRE "TIMEZONE" HERE
]

# ----------------------------------------------------------------------
# Core decrypt/load/validate (patched to use the resolver)
# ----------------------------------------------------------------------

def _decrypt_env_bot(enc_path: Path, encryption_key: str) -> Dict[str, Any]:
    try:
        logger.debug(f"Decrypting .env_bot.enc at {enc_path}")
        with open(enc_path, "rb") as file:
            encrypted_data = file.read()
        fernet = Fernet(encryption_key.encode())
        decrypted_data = fernet.decrypt(encrypted_data).decode()
        logger.debug(".env_bot.enc decrypted successfully")
        return json.loads(decrypted_data)
    except Exception as e:
        logger.error(f"Failed to decrypt .env_bot.enc at {enc_path}: {e}")
        raise RuntimeError(f"Failed to decrypt .env_bot.enc at {enc_path}: {e}")

def load_env_bot() -> Dict[str, Any]:
    enc_path, key_path, tried_enc, tried_key = _resolve_encrypted_paths()

    if key_path is None:
        tried_str = ", ".join(str(p) for p in tried_key)
        logger.error(f"ENV_BOT_KEY not found. Tried: {tried_str}")
        raise RuntimeError(f"ENV_BOT_KEY not found. Tried: {tried_str}")

    if enc_path is None:
        tried_str = ", ".join(str(p) for p in tried_enc)
        logger.error(f".env_bot.enc not found. Tried: {tried_str}")
        raise RuntimeError(f".env_bot.enc not found. Tried: {tried_str}")

    encryption_key = key_path.read_text(encoding="utf-8").strip()
    logger.debug(f"Read encryption key from {key_path}")
    config = _decrypt_env_bot(enc_path, encryption_key)

    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        logger.error(f"Missing required keys in .env_bot: {missing}")
        raise KeyError(f"Missing required keys in .env_bot: {missing}")

    logger.debug(f".env_bot keys present: {list(config.keys())}")
    for key, val in list(config.items()):
        if isinstance(val, str):
            val_lc = val.lower()
            if val_lc == "true":
                config[key] = True
                logger.debug(f"Key {key}: converted string 'true' to boolean True")
            elif val_lc == "false":
                config[key] = False
                logger.debug(f"Key {key}: converted string 'false' to boolean False")
    return config

def validate_bot_config(config: Dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        logger.error(f"Missing required keys during validation: {missing}")
        raise ValueError(f"Missing required keys: {missing}")
    alloc = float(config.get("TOTAL_ALLOCATION", 0))
    if not (0 < alloc <= 1):
        logger.error("TOTAL_ALLOCATION must be between 0 and 1.")
        raise ValueError("TOTAL_ALLOCATION must be between 0 and 1.")
    export_mode = config.get("LEDGER_EXPORT_MODE")
    if export_mode not in ("auto", "off"):
        logger.error("LEDGER_EXPORT_MODE must be 'auto' or 'off'.")
        raise ValueError("LEDGER_EXPORT_MODE must be 'auto' or 'off'.")

def get_bot_config() -> Dict[str, Any]:
    logger.debug("Loading bot config from .env_bot.enc")
    config = load_env_bot()
    logger.debug("Validating bot config")
    validate_bot_config(config)
    logger.debug("Bot config loaded and validated successfully")
    return config

def load_env_var(key: str, fallback: Any = None) -> Any:
    try:
        config = get_bot_config()
        return config.get(key, fallback)
    except Exception:
        return fallback

def update_env_var(key: str, value: Any) -> None:
    enc_path, key_path, _, _ = _resolve_encrypted_paths()
    if enc_path is None or key_path is None:
        raise RuntimeError("Cannot update: encrypted file or key not found (check TBOT_ENV_BOT_ENC_PATH/TBOT_ENV_BOT_KEY_PATH or default locations).")
    encryption_key = key_path.read_text(encoding="utf-8").strip()
    with open(enc_path, "rb") as f:
        encrypted_data = f.read()
    decrypted = Fernet(encryption_key.encode()).decrypt(encrypted_data).decode()
    config = json.loads(decrypted)
    config[key] = value
    updated_encrypted = Fernet(encryption_key.encode()).encrypt(json.dumps(config).encode())
    with open(enc_path, "wb") as f:
        f.write(updated_encrypted)

load_env_bot_config = get_bot_config

# ----------------------------------------------------------------------
# NEW: Explicit getters for schedule values
# NOTE: RUNTIME MUST USE ONLY THE *_UTC GETTERS BELOW.
# *_LOCAL getters are provided for UI/display; do not use them in scheduling logic.
# ----------------------------------------------------------------------

def get_open_time_utc() -> str:
    """Return START_TIME_OPEN as 'HH:MM' (UTC)."""
    v = load_env_var("START_TIME_OPEN", "")
    return str(v or "").strip()

def get_mid_time_utc() -> str:
    """Return START_TIME_MID as 'HH:MM' (UTC)."""
    v = load_env_var("START_TIME_MID", "")
    return str(v or "").strip()

def get_close_time_utc() -> str:
    """Return START_TIME_CLOSE as 'HH:MM' (UTC)."""
    v = load_env_var("START_TIME_CLOSE", "")
    return str(v or "").strip()

def get_market_close_utc() -> str:
    """Return MARKET_CLOSE_UTC as 'HH:MM' (UTC)."""
    v = load_env_var("MARKET_CLOSE_UTC", "")
    return str(v or "").strip()

def get_timezone() -> str:
    """
    Return configured TIMEZONE (IANA tz like 'America/New_York').
    Not required by REQUIRED_KEYS; defaults to 'UTC' if missing.
    """
    v = load_env_var("TIMEZONE", "UTC")
    return str(v or "UTC").strip()

# --- UI-only LOCAL getters (for display/forms). DO NOT use in runtime scheduling. ---

def get_open_time_local() -> str:
    """UI-only: START_TIME_OPEN_LOCAL as 'HH:MM' in configured TIMEZONE."""
    v = load_env_var("START_TIME_OPEN_LOCAL", "")
    return str(v or "").strip()

def get_mid_time_local() -> str:
    """UI-only: START_TIME_MID_LOCAL as 'HH:MM' in configured TIMEZONE."""
    v = load_env_var("START_TIME_MID_LOCAL", "")
    return str(v or "").strip()

def get_close_time_local() -> str:
    """UI-only: START_TIME_CLOSE_LOCAL as 'HH:MM' in configured TIMEZONE."""
    v = load_env_var("START_TIME_CLOSE_LOCAL", "")
    return str(v or "").strip()

# ----------------------------------------------------------------------
# NEW: Supervisor delay/after-close getters (numeric with sane defaults)
# ----------------------------------------------------------------------

def get_sup_open_delay_min() -> int:
    """
    Minutes to wait AFTER the OPEN strategy **start** before running holdings maintenance.
    Default: 10.
    """
    v = load_env_var("SUP_OPEN_DELAY_MIN", 10)
    try:
        return int(v)
    except Exception:
        return 10

def get_sup_mid_delay_min() -> int:
    """
    Minutes to wait AFTER the MID strategy **start** before running holdings maintenance.
    Default: fall back to SUP_OPEN_DELAY_MIN (or 60 if unset).
    """
    fallback = load_env_var("SUP_OPEN_DELAY_MIN", 60)
    v = load_env_var("SUP_MID_DELAY_MIN", fallback)
    try:
        return int(v)
    except Exception:
        try:
            return int(fallback)
        except Exception:
            return 60

def get_sup_universe_after_close_min() -> int:
    """
    Minutes to wait AFTER the CLOSE strategy **start** before running the universe build.
    Default: 120.
    """
    v = load_env_var("SUP_UNIVERSE_AFTER_CLOSE_MIN", 120)
    try:
        return int(v)
    except Exception:
        return 120
