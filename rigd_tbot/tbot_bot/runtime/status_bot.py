# tbot_bot/runtime/status_bot.py
# Tracks and records state changes

"""
status_bot.py – Tracks and exposes the current state of the bot for UI or external monitoring.
Used by status_web.py and internal logging for diagnostics and dashboard reporting.
"""

import time
from datetime import datetime
from threading import Lock, Thread
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now          # UPDATED: Import from utils_time
from tbot_bot.support.utils_log import log_event     # UPDATED: Import from utils_log

# Thread-safe singleton class to hold live bot status
class BotStatus:
    def __init__(self):
        self.lock = Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.state = "idle"  # Initial state on startup
            self.active_strategy = None
            self.timestamp = utc_now().isoformat()
            self.trade_count = 0
            self.error_count = 0
            self.enabled_strategies = {
                "open": False,
                "mid": False,
                "close": False
            }
            self.broker_code = "undefined"  # Placeholder; injected via config
            self.broker_mode = "single"     # PAPER mode removed in v1.0.0
            self.is_live_mode = True        # Always true under single-broker architecture
            self.version = "v1.0.0"
            self.daily_loss_limit = 0.05
            self.max_risk_per_trade = 0.025

    def update_config(self, config: dict):
        with self.lock:
            self.enabled_strategies["open"] = config.get("STRAT_OPEN_ENABLED", False)
            self.enabled_strategies["mid"] = config.get("STRAT_MID_ENABLED", False)
            self.enabled_strategies["close"] = config.get("STRAT_CLOSE_ENABLED", False)

            self.broker_code = config.get("BROKER_NAME", "undefined").lower()  # Replaces deprecated BROKER_CODE
            self.broker_mode = "single"  # All bots now run in unified live mode (see doc 04)
            self.is_live_mode = True     # Legacy PAPER_MODE logic removed

            self.version = config.get("VERSION_TAG", "v1.0.0")
            self.daily_loss_limit = config.get("DAILY_LOSS_LIMIT", 0.05)
            self.max_risk_per_trade = config.get("MAX_RISK_PER_TRADE", 0.025)

    def set_state(self, new_state: str):
        with self.lock:
            self.state = new_state
            self.timestamp = utc_now().isoformat()

    def set_strategy(self, strategy_name: str):
        with self.lock:
            self.active_strategy = strategy_name

    def increment_trade_count(self):
        with self.lock:
            self.trade_count += 1

    def increment_error_count(self):
        with self.lock:
            self.error_count += 1

    def to_dict(self):
        with self.lock:
            return {
                "timestamp": self.timestamp,
                "state": self.state,
                "active_strategy": self.active_strategy,
                "trade_count": self.trade_count,
                "error_count": self.error_count,
                "enabled_strategies": self.enabled_strategies,
                "broker_code": self.broker_code,
                "broker_mode": self.broker_mode,
                "is_live_mode": self.is_live_mode,
                "version": self.version,
                "daily_loss_limit": self.daily_loss_limit,
                "max_risk_per_trade": self.max_risk_per_trade
            }

# Global instance
bot_status = BotStatus()

# Initialize with decrypted config
config = get_bot_config()
bot_status.update_config(config)

def update_bot_state(state: str = None, strategy: str = None, error: bool = False, trade: bool = False):
    """
    Convenience wrapper to update runtime bot status.
    Called throughout lifecycle to reflect state transitions and counters.
    """
    if state:
        bot_status.set_state(state)
    if strategy:
        bot_status.set_strategy(strategy)
    if error:
        bot_status.increment_error_count()
    if trade:
        bot_status.increment_trade_count()

def start_heartbeat(interval: int = 15):
    """
    Launches a background thread to log heartbeat every `interval` seconds.
    Provides real-time confirmation of bot liveness for watchdogs and UI dashboards.
    """
    def heartbeat_loop():
        while True:
            status = bot_status.to_dict()
            log_event("heartbeat", f"Heartbeat OK – State: {status['state']}, Strategy: {status['active_strategy']}")
            time.sleep(interval)

    thread = Thread(target=heartbeat_loop, daemon=True)
    thread.start()
