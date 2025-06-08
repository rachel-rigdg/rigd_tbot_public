# tbot_bot/config/env_bot.py
# summary: Validates and parses .env_bot configuration (encrypted or plaintext, but never auto-loads at module level).
# All config access must be explicit and deferred—no module-level loading permitted.

import json
from cryptography.fernet import Fernet
from pathlib import Path
from typing import Any, Dict

# Correct paths for encrypted bot config
CONFIG_PATH = Path(__file__).resolve().parent.parent / "support" / ".env_bot"
ENCRYPTED_CONFIG_PATH = CONFIG_PATH.with_suffix(".enc")
KEY_PATH = Path(__file__).resolve().parent.parent / "storage" / "keys" / "env_bot.key"

REQUIRED_KEYS = [
    # Core identity (injected via Web UI bootstrap)
    "VERSION_TAG", "BUILD_MODE",
    # Control flags
    "DISABLE_ALL_TRADES", "ENABLE_LOGGING", "LOG_FORMAT", "DEBUG_LOG_LEVEL",
    "TRADE_CONFIRMATION_REQUIRED", "API_RETRY_LIMIT", "API_TIMEOUT",
    "FRACTIONAL", "TOTAL_ALLOCATION", "MAX_TRADES", "WEIGHTS",
    "DAILY_LOSS_LIMIT", "MAX_RISK_PER_TRADE", "MAX_OPEN_POSITIONS",
    "MIN_PRICE", "MAX_PRICE", "MIN_VOLUME_THRESHOLD",
    # Strategy control
    "STRATEGY_SEQUENCE", "STRATEGY_OVERRIDE", "TRADING_DAYS", "SLEEP_TIME",
    # Strategy: OPEN
    "STRAT_OPEN_ENABLED", "START_TIME_OPEN", "OPEN_ANALYSIS_TIME",
    "OPEN_BREAKOUT_TIME", "OPEN_MONITORING_TIME", "STRAT_OPEN_BUFFER", "SHORT_TYPE_OPEN",
    "MAX_GAP_PCT_OPEN", "MIN_MARKET_CAP_OPEN", "MAX_MARKET_CAP_OPEN",
    # Strategy: MID
    "STRAT_MID_ENABLED", "START_TIME_MID", "MID_ANALYSIS_TIME",
    "MID_BREAKOUT_TIME", "MID_MONITORING_TIME", "STRAT_MID_VWAP_THRESHOLD", "SHORT_TYPE_MID",
    "MAX_GAP_PCT_MID", "MIN_MARKET_CAP_MID", "MAX_MARKET_CAP_MID",
    # Strategy: CLOSE
    "STRAT_CLOSE_ENABLED", "START_TIME_CLOSE", "CLOSE_ANALYSIS_TIME",
    "CLOSE_BREAKOUT_TIME", "CLOSE_MONITORING_TIME", "STRAT_CLOSE_VIX_THRESHOLD", "SHORT_TYPE_CLOSE",
    "MAX_GAP_PCT_CLOSE", "MIN_MARKET_CAP_CLOSE", "MAX_MARKET_CAP_CLOSE",
    # Notifications
    "NOTIFY_ON_FILL", "NOTIFY_ON_EXIT",
    # Reporting
    "LEDGER_EXPORT_MODE"
]

def decrypt_env_bot(encryption_key: str) -> Dict[str, Any]:
    """
    Decrypts the .env_bot.enc file using the provided Fernet key and parses JSON.
    """
    try:
        with open(ENCRYPTED_CONFIG_PATH, "rb") as file:
            encrypted_data = file.read()
        fernet = Fernet(encryption_key.encode())
        decrypted_data = fernet.decrypt(encrypted_data).decode()
        return json.loads(decrypted_data)
    except Exception as e:
        raise RuntimeError(f"Failed to decrypt .env_bot.enc: {e}")

def load_env_bot(test_mode: bool = False) -> Dict[str, Any]:
    """
    Loads the bot configuration dictionary.
    If test_mode=True, allows reading plaintext .env_bot. Otherwise, only uses encrypted .env_bot.enc + env_bot.key.
    Never called at module import time—only after bootstrap.
    """
    if test_mode:
        try:
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to load plain .env_bot file in test mode: {e}")
    else:
        if not KEY_PATH.exists():
            raise RuntimeError(f"ENV_BOT_KEY missing at expected path: {KEY_PATH}")
        encryption_key = KEY_PATH.read_text(encoding="utf-8").strip()
        config = decrypt_env_bot(encryption_key)

    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        raise KeyError(f"Missing required keys in .env_bot: {missing}")

    # Convert booleans as needed
    for key, val in list(config.items()):
        if isinstance(val, str):
            val_lc = val.lower()
            if val_lc == "true":
                config[key] = True
            elif val_lc == "false":
                config[key] = False

    return config

def get_env_bot_path() -> str:
    """
    Returns the resolved path to .env_bot (plaintext). Used only for test/dev, not production.
    """
    return str(CONFIG_PATH)

def validate_bot_config(config: Dict[str, Any]) -> None:
    """
    Validates presence and logic of required config values (for write_settings, etc).
    Throws ValueError on missing or invalid entries.
    """
    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        raise ValueError(f"Missing required keys: {missing}")
    alloc = float(config.get("TOTAL_ALLOCATION", 0))
    if not (0 < alloc <= 1):
        raise ValueError("TOTAL_ALLOCATION must be between 0 and 1.")
    export_mode = config.get("LEDGER_EXPORT_MODE")
    if export_mode not in ("auto", "off"):
        raise ValueError("LEDGER_EXPORT_MODE must be 'auto' or 'off'.")

def get_bot_config() -> Dict[str, Any]:
    """
    Loads the current (decrypted) bot config (never called at module import time).
    """
    return load_env_bot()

# NOTE: No top-level auto-loads; all config usage is deferred to after bootstrap.
