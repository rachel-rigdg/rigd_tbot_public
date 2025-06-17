# tbot_bot/runtime/status_bot.py
# Tracks and records state changes

"""
status_bot.py – Tracks and exposes the current state of the bot for UI or external monitoring.
Used by status_web.py and internal logging for diagnostics and dashboard reporting.
Implements exhaustive status tracking and win_rate calculation per RIGD_TradingBot spec.
Writes live status only to tbot_bot/output/logs/status.json (no identity subdir).
"""

import time
import json
from datetime import datetime
from threading import Lock, Thread
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event, get_log_settings
from pathlib import Path

STATUS_FILE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / "logs" / "status.json"

def ensure_status_dir():
    STATUS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

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
            self.win_trades = 0
            self.loss_trades = 0
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
            self.pnl = 0.0
            self.win_rate = 0.0

    def update_config(self, config: dict):
        with self.lock:
            self.enabled_strategies["open"] = config.get("STRAT_OPEN_ENABLED", False)
            self.enabled_strategies["mid"] = config.get("STRAT_MID_ENABLED", False)
            self.enabled_strategies["close"] = config.get("STRAT_CLOSE_ENABLED", False)

            self.broker_code = config.get("BROKER_NAME", "undefined").lower()
            self.broker_mode = "single"
            self.is_live_mode = True

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

    def increment_trade_count(self, win=False, pnl=0.0):
        with self.lock:
            self.trade_count += 1
            if win:
                self.win_trades += 1
            else:
                self.loss_trades += 1
            self
