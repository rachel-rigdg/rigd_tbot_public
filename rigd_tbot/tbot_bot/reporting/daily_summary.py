# tbot_bot/reporting/daily_summary.py
# WORKER. Only launched by main.py. Writes daily trade summary to /output/summaries/{BOT_IDENTITY}_BOT_daily_summary.json
# All file paths are resolved via path_resolver.py (never hardcoded).
# Supports TEST_MODE separation if needed by output path routing.

import os
import json
from datetime import datetime
from typing import List, Dict
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path

BOT_IDENTITY = get_bot_identity()
SUMMARY_FILE = f"{BOT_IDENTITY}_BOT_daily_summary.json"

_summary_data = {
    "trades": [],
    "total_PnL": 0.0,
    "wins": 0,
    "losses": 0,
    "errors": 0,
    "start_time": datetime.utcnow().isoformat()
}

def append_trade_to_summary(trade: Dict):
    global _summary_data
    pnl = trade.get("PnL", 0.0)
    _summary_data["trades"].append(trade)
    _summary_data["total_PnL"] += pnl
    if pnl > 0:
        _summary_data["wins"] += 1
    elif pnl < 0:
        _summary_data["losses"] += 1

def increment_error_count():
    global _summary_data
    _summary_data["errors"] += 1

def finalize_summary(extra_stats: Dict = None):
    global _summary_data
    _summary_data["end_time"] = datetime.utcnow().isoformat()
    if extra_stats:
        _summary_data.update(extra_stats)
    try:
        full_path = get_output_path(bot_identity=BOT_IDENTITY, category="summaries", filename=SUMMARY_FILE)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(_summary_data, f, indent=2)
        log_event("daily_summary", f"Summary written to {SUMMARY_FILE}")
    except Exception as e:
        log_event("daily_summary", f"Failed to write summary: {e}", level="error")

def get_summary_data() -> Dict:
    return _summary_data
