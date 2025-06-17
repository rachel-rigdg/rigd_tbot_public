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
            self.pnl += pnl
            self._update_win_rate()

    def increment_error_count(self):
        with self.lock:
            self.error_count += 1

    def set_trade_result(self, win: bool, pnl: float = 0.0):
        with self.lock:
            self.trade_count += 1
            if win:
                self.win_trades += 1
            else:
                self.loss_trades += 1
            self.pnl += pnl
            self._update_win_rate()

    def set_pnl(self, pnl: float):
        with self.lock:
            self.pnl = pnl

    def _update_win_rate(self):
        if self.trade_count > 0:
            self.win_rate = round(100.0 * self.win_trades / self.trade_count, 2)
        else:
            self.win_rate = 0.0

    def to_dict(self):
        with self.lock:
            return {
                "timestamp": self.timestamp,
                "state": self.state,
                "active_strategy": self.active_strategy,
                "trade_count": self.trade_count,
                "win_trades": self.win_trades,
                "loss_trades": self.loss_trades,
                "error_count": self.error_count,
                "enabled_strategies": self.enabled_strategies,
                "broker_code": self.broker_code,
                "broker_mode": self.broker_mode,
                "is_live_mode": self.is_live_mode,
                "version": self.version,
                "daily_loss_limit": self.daily_loss_limit,
                "max_risk_per_trade": self.max_risk_per_trade,
                "pnl": self.pnl,
                "win_rate": self.win_rate
            }

    def save_status(self):
        status_dict = self.to_dict()
        ensure_status_dir()
        try:
            with open(STATUS_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(status_dict, f, indent=2)
        except Exception as e:
            print(f"[status_bot] ERROR: Failed to write status.json: {e}")

# Global instance
bot_status = BotStatus()

# Always ensure status.json exists on import
try:
    config = get_bot_config()
    bot_status.update_config(config)
    bot_status.save_status()
except Exception:
    bot_status.save_status()

def update_bot_state(state: str = None, strategy: str = None, error: bool = False, trade: bool = False, win: bool = None, pnl: float = 0.0):
    if state:
        bot_status.set_state(state)
    if strategy:
        bot_status.set_strategy(strategy)
    if error:
        bot_status.increment_error_count()
    if trade:
        if win is not None:
            bot_status.set_trade_result(win=win, pnl=pnl)
        else:
            bot_status.increment_trade_count()
    bot_status.save_status()

def start_heartbeat(interval: int = 15):
    def heartbeat_loop():
        from tbot_bot.support.utils_log import get_log_settings
        DEBUG_LOG_LEVEL, ENABLE_LOGGING, LOG_FORMAT = get_log_settings()
        while True:
            status = bot_status.to_dict()
            if DEBUG_LOG_LEVEL != "quiet":
                log_event("heartbeat", f"Heartbeat OK – State: {status['state']}, Strategy: {status['active_strategy']}, Win Rate: {status['win_rate']}%")
            bot_status.save_status()
            time.sleep(interval)
    thread = Thread(target=heartbeat_loop, daemon=True)
    thread.start()
