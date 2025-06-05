# tbot_bot/enhancements/tuning_tracker.py
# Tracks and evaluates past strategy performance for tuning guidance

import os
import json
import statistics
from datetime import datetime, timezone
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_utils import resolve_output_path  # UPDATED
from tbot_bot.support.utils_log import log_event  # UPDATED

# Load runtime config
config = get_bot_config()
ENABLE_TUNING_TRACKER = config.get("ENABLE_TUNING_TRACKER", "false").lower() == "true"
LOG_FORMAT = config.get("LOG_FORMAT", "json")

# Constants
STRATEGIES = ["open", "mid", "close"]
HISTORY_DAYS = int(config.get("OPTIMIZER_BACKTEST_LOOKBACK_DAYS", 30))
SUMMARY_OUTPUT_PATH = resolve_output_path("tuning_summary", file_type="json", create=True)
TRADE_HISTORY_DIR = resolve_output_path("trades", ensure_exists=True)


def load_trades(strategy_name):
    filename = os.path.join(TRADE_HISTORY_DIR, f"{strategy_name}_trade_history.{LOG_FORMAT}")
    if not os.path.exists(filename):
        return []
    with open(filename, "r") as f:
        return json.load(f) if LOG_FORMAT == "json" else []

def compute_metrics(trades):
    if not trades:
        return {"win_rate": 0, "avg_pnl": 0, "max_gain": 0, "max_loss": 0, "trade_count": 0}

    wins = [t for t in trades if t.get("PnL", 0) > 0]
    losses = [t for t in trades if t.get("PnL", 0) <= 0]
    pnl_values = [t.get("PnL", 0) for t in trades]

    return {
        "win_rate": round(len(wins) / len(trades) * 100, 2),
        "avg_pnl": round(statistics.mean(pnl_values), 4),
        "max_gain": round(max(pnl_values), 4),
        "max_loss": round(min(pnl_values), 4),
        "trade_count": len(trades)
    }

def summarize_tuning_results():
    results = {"timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()}
    for strat in STRATEGIES:
        trades = load_trades(strat)
        results[strat] = compute_metrics(trades)

    os.makedirs(os.path.dirname(SUMMARY_OUTPUT_PATH), exist_ok=True)
    with open(SUMMARY_OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    log_event(f"Tuning summary saved to {SUMMARY_OUTPUT_PATH}", category="TUNING_TRACKER")

def self_check():
    # Basic file path validation and config toggle test
    try:
        assert isinstance(ENABLE_TUNING_TRACKER, bool)
        assert isinstance(SUMMARY_OUTPUT_PATH, str)
        assert os.path.isdir(TRADE_HISTORY_DIR)
        return True
    except Exception as e:
        log_event(f"Tuning tracker self_check failed: {e}", level="error")
        return False

if __name__ == "__main__":
    if ENABLE_TUNING_TRACKER:
        if self_check():
            summarize_tuning_results()
        else:
            log_event("Tuning tracker self-check failed; skipping execution", level="error")
