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
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.decrypt_secrets import decrypt_json
from pathlib import Path
import os

BOT_STATE_FILE = Path(os.getenv("CONTROL_DIR", Path(__file__).resolve().parents[2] / "control")) / "bot_state.txt"

# Allowed states
ALLOWED_STATES = [
    "idle",
    "analyzing",
    "trading",
    "monitoring",
    "provisioning",
    "bootstrapping",
    "updating",
    "shutdown",
    "error"
]

# Thread-safe singleton class to hold live bot status
class BotStatus:
    def __init__(self):
        self.lock = Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.state = "idle"
            self.active_strategy = None
            self.timestamp = utc_now().isoformat()
            self.trade_count = 0
            self.error_count = 0
            self.enabled_strategies = {
                "open": False,
                "mid": False,
                "close": False
            }
            self.broker_code = "undefined"
            self.broker_mode = "single"
            self.is_live_mode = True
            self.version = "v1.0.0"
            self.daily_loss_limit = 0.05
            self.max_risk_per_trade = 0.025

    def update_config(self, config: dict, broker_creds: dict = None):
        with self.lock:
            self.enabled_strategies["open"] = config.get("STRAT_OPEN_ENABLED", False)
            self.enabled_strategies["mid"] = config.get("STRAT_MID_ENABLED", False)
            self.enabled_strategies["close"] = config.get("STRAT_CLOSE_ENABLED", False)
            if broker_creds and broker_creds.get("BROKER_CODE"):
                self.broker_code = broker_creds.get("BROKER_CODE", "undefined").lower()
            else:
                self.broker_code = config.get("BROKER_NAME", "undefined").lower()
            self.broker_mode = "single"
            self.is_live_mode = True
            self.version = config.get("VERSION_TAG", "v1.0.0")
            self.daily_loss_limit = config.get("DAILY_LOSS_LIMIT", 0.05)
            self.max_risk_per_trade = config.get("MAX_RISK_PER_TRADE", 0.025)

    def set_state(self, new_state: str):
        with self.lock:
            if new_state in ALLOWED_STATES:
                self.state = new_state
            else:
                self.state = "error"
            self.timestamp = utc_now().isoformat()
            # Write state to disk for UI/status monitoring
            BOT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
                f.write(self.state)

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

# Initialize with decrypted config and broker creds
config = get_bot_config()
try:
    broker_creds = decrypt_json("broker_credentials")
except Exception:
    broker_creds = {}
bot_status.update_config(config, broker_creds)

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
