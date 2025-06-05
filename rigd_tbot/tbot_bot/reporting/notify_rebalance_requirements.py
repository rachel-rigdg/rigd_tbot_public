# tbot_bot/reporting/notify_rebalance_requirements.py
# Monitors current float and triggers rebalance notification if deviation exceeds threshold

import time
from tbot_bot.config.env_bot import env_config
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.identity_utils import get_bot_identity
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path
from tbot_bot.accounting.accounting_api import post_rebalance_entry
from tbot_bot.risk.risk_bot import is_safe_mode
from tbot_bot.float_bot import get_current_float  # Must be implemented in float_bot.py

REBALANCE_ENABLED = env_config.get("REBALANCE_ENABLED", False)
REBALANCE_THRESHOLD = float(env_config.get("REBALANCE_THRESHOLD", 0.10))
REBALANCE_CHECK_INTERVAL = int(env_config.get("REBALANCE_CHECK_INTERVAL", 3600))  # Seconds

def get_target_float() -> float:
    """
    Reads the target float value for this bot instance from a file.
    Returns:
        float or None
    """
    try:
        target_path = get_output_path(category="ledgers", filename="float_target.txt")
        with open(target_path, "r") as f:
            return float(f.read().strip())
    except Exception as e:
        log_event("rebalance_monitor", f"Failed to read float target: {e}", level="error")
        return None

def notify_if_out_of_balance():
    """
    Compares current float to target. Logs and posts rebalance entry if deviation exceeds threshold.
    """
    if not REBALANCE_ENABLED:
        log_event("rebalance_monitor", "Rebalance monitoring disabled.")
        return

    if not is_safe_mode():
        log_event("rebalance_monitor", "Unsafe mode active. Skipping float check.")
        return

    current_float = get_current_float()
    target_float = get_target_float()
    if current_float is None or target_float is None:
        log_event("rebalance_monitor", "Missing float data. Cannot evaluate.")
        return

    deviation = abs(current_float - target_float) / target_float
    if deviation > REBALANCE_THRESHOLD:
        log_event("rebalance_monitor", f"Float deviation {deviation:.2%} exceeds threshold.")
        identity = get_bot_identity()
        post_rebalance_entry(
            broker=identity["BROKER_CODE"],
            target=target_float,
            actual=current_float,
            timestamp=utc_now()
        )

def run_rebalance_monitor_loop():
    """
    Runs continuous float check loop on interval.
    """
    while True:
        notify_if_out_of_balance()
        time.sleep(REBALANCE_CHECK_INTERVAL)
