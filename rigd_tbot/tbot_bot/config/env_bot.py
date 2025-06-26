# tbot_bot/config/env_bot.py
# summary: Validates and parses .env_bot configuration (encrypted only, never auto-loads at module level).
# All config access must be explicit and deferred—no module-level loading permitted.
# Provides TEST_MODE detection as per latest spec.

import json
import logging
from cryptography.fernet import Fernet
from pathlib import Path
from typing import Any, Dict

ENCRYPTED_CONFIG_PATH = Path(__file__).resolve().parent.parent / "support" / ".env_bot.enc"
KEY_PATH = Path(__file__).resolve().parent.parent / "storage" / "keys" / "env_bot.key"
CONTROL_DIR = Path(__file__).resolve().parent.parent / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

REQUIRED_KEYS = [
    "VERSION_TAG", "BUILD_MODE",
    "DISABLE_ALL_TRADES", "ENABLE_LOGGING", "LOG_FORMAT", "DEBUG_LOG_LEVEL",
    "TRADE_CONFIRMATION_REQUIRED", "API_RETRY_LIMIT", "API_TIMEOUT",
    "FRACTIONAL", "TOTAL_ALLOCATION", "MAX_TRADES", "WEIGHTS",
    "DAILY_LOSS_LIMIT", "MAX_RISK_PER_TRADE", "MAX_OPEN_POSITIONS",
    "MIN_PRICE", "MAX_PRICE", "MIN_VOLUME_THRESHOLD",
    "STRATEGY_SEQUENCE", "STRATEGY_OVERRIDE", "TRADING_DAYS", "SLEEP_TIME",
    "STRAT_OPEN_ENABLED", "START_TIME_OPEN", "OPEN_ANALYSIS_TIME",
    "OPEN_BREAKOUT_TIME", "OPEN_MONITORING_TIME", "STRAT_OPEN_BUFFER", "SHORT_TYPE_OPEN",
    "MAX_GAP_PCT_OPEN", "MIN_MARKET_CAP_OPEN", "MAX_MARKET_CAP_OPEN",
    "STRAT_MID_ENABLED", "START_TIME_MID", "MID_ANALYSIS_TIME",
    "MID_BREAKOUT_TIME", "MID_MONITORING_TIME", "STRAT_MID_VWAP_THRESHOLD", "SHORT_TYPE_MID",
    "MAX_GAP_PCT_MID", "MIN_MARKET_CAP_MID", "MAX_MARKET_CAP_MID",
    "STRAT_CLOSE_ENABLED", "START_TIME_CLOSE", "CLOSE_ANALYSIS_TIME",
    "CLOSE_BREAKOUT_TIME", "CLOSE_MONITORING_TIME", "STRAT_CLOSE_VIX_THRESHOLD", "SHORT_TYPE_CLOSE",
    "MAX_GAP_PCT_CLOSE", "MIN_MARKET_CAP_CLOSE", "MAX_MARKET_CAP_CLOSE",
    "NOTIFY_ON_FILL", "NOTIFY_ON_EXIT",
    "LEDGER_EXPORT_MODE"
]

logger = logging.getLogger(__name__)

def decrypt_env_bot(encryption_key: str) -> Dict[str, Any]:
    try:
        logger.debug(f"Decrypting .env_bot.enc at {ENCRYPTED_CONFIG_PATH}")
        with open(ENCRYPTED_CONFIG_PATH, "rb") as file:
            encrypted_data = file.read()
        fernet = Fernet(encryption_key.encode())
        decrypted_data = fernet.decrypt(encrypted_data).decode()
        logger.debug(".env_bot.enc decrypted successfully")
        return json.loads(decrypted_data)
    except Exception as e:
        logger.error(f"Failed to decrypt .env_bot.enc: {e}")
        raise RuntimeError(f"Failed to decrypt .env_bot.enc: {e}")

def load_env_bot() -> Dict[str, Any]:
    if not KEY_PATH.exists():
        logger.error(f"ENV_BOT_KEY missing at expected path: {KEY_PATH}")
        raise RuntimeError(f"ENV_BOT_KEY missing at expected path: {KEY_PATH}")
    encryption_key = KEY_PATH.read_text(encoding="utf-8").strip()
    logger.debug(f"Read encryption key from {KEY_PATH}")
    config = decrypt_env_bot(encryption_key)
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

def is_test_mode() -> bool:
    """Returns True if test_mode.flag exists, else False. Used for main.py/test awareness."""
    return TEST_MODE_FLAG.exists()

load_env_bot_config = get_bot_config
