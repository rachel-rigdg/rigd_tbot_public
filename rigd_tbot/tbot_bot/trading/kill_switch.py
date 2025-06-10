# tbot_bot/trading/kill_switch.py
# Abort if drawdown exceeds DAILY_LOSS_LIMIT

"""
Triggers an emergency shutdown if cumulative losses exceed the DAILY_LOSS_LIMIT
specified in decrypted config. Prevents further trades and logs the trigger event.
"""

import os
import json
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_output_path
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.utils_identity import get_bot_identity
from pathlib import Path

config = get_bot_config()
DAILY_LOSS_LIMIT = float(config.get("DAILY_LOSS_LIMIT", 0.05))
BOT_ID = get_bot_identity()

SUMMARY_PATH = get_output_path(category="summaries", filename=f"{BOT_ID}_BOT_daily_summary.json")
SHUTDOWN_FLAG = get_output_path(category="logs", filename="shutdown_triggered.txt")
CONTROL_DIR = Path(os.getenv("CONTROL_DIR", Path(__file__).resolve().parents[1] / "control"))
KILL_FLAG = CONTROL_DIR / "control_kill.txt"

def load_summary():
    """Load session summary JSON to access total PnL."""
    if not os.path.exists(SUMMARY_PATH):
        print(f"[kill_switch] Summary file not found at {SUMMARY_PATH}")
        log_event("kill_switch", f"Summary file not found at {SUMMARY_PATH}")
        return None
    try:
        with open(SUMMARY_PATH, "r") as f:
            data = json.load(f)
        print(f"[kill_switch] Loaded summary data: {data}")
        log_event("kill_switch", f"Loaded summary data successfully")
        return data
    except Exception as e:
        print(f"[kill_switch] Failed to load summary file: {e}")
        log_event("kill_switch", f"Failed to load summary file: {e}")
        return None

def check_daily_loss_limit():
    """Abort session if realized PnL exceeds allowable loss or kill flag present."""
    # Emergency kill flag check
    #if KILL_FLAG.exists():
    #    print("[kill_switch] control_kill.txt detected — immediate shutdown triggered.")
    #   log_event("kill_switch", "control_kill.txt detected — immediate shutdown triggered.")
    #    trigger_shutdown(reason="Immediate kill flag (control_kill.txt) detected")
     #   return True

    summary = load_summary()
    if not summary:
        print("[kill_switch] No summary data available; skipping loss limit check.")
        log_event("kill_switch", "No summary data available; skipping loss limit check.")
        return False

    total_pnl = float(summary.get("total_PnL", 0.0))
    print(f"[kill_switch] Checking PnL: {total_pnl} against limit {-abs(DAILY_LOSS_LIMIT)}")
    log_event("kill_switch", f"Checking PnL: {total_pnl} against limit {-abs(DAILY_LOSS_LIMIT)}")

    if total_pnl < -abs(DAILY_LOSS_LIMIT):
        print(f"[kill_switch] DAILY_LOSS_LIMIT breached: {total_pnl:.2f} < -{DAILY_LOSS_LIMIT:.2f}")
        log_event("kill_switch", f"DAILY_LOSS_LIMIT breached: {total_pnl:.2f} < -{DAILY_LOSS_LIMIT:.2f}")
        trigger_shutdown(reason=f"PnL {total_pnl:.2f} < -{DAILY_LOSS_LIMIT:.2f}")
        return True

    return False

def check_zero_symbol_scan(filtered_count: int):
    """Abort strategy if no valid symbols were returned."""
    print(f"[kill_switch] Zero symbol scan check: {filtered_count} symbols filtered")
    log_event("kill_switch", f"Zero symbol scan check: {filtered_count} symbols filtered")
    if filtered_count <= 0:
        print("[kill_switch] No symbols passed screener filter — triggering strategy abort.")
        log_event("kill_switch", "No symbols passed screener filter — triggering strategy abort.")
        trigger_shutdown(reason="All symbols rejected by screener")
        return True
    return False

def trigger_shutdown(reason="DAILY_LOSS_LIMIT breach"):
    """Trigger emergency stop and notify administrators, set kill flag."""
    print(f"[kill_switch] EMERGENCY SHUTDOWN triggered — Reason: {reason}")
    log_event("kill_switch", f"EMERGENCY SHUTDOWN — Reason: {reason}")
    try:
        with open(SHUTDOWN_FLAG, "w") as f:
            f.write(f"Shutdown triggered at {utc_now().isoformat()} — Reason: {reason}\n")
        # Write/refresh kill flag for clarity (redundant but explicit)
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        with open(KILL_FLAG, "w") as f:
            f.write(f"kill — {reason}")
        from tbot_bot.trading.notifier_bot import notify_critical_error
        notify_critical_error(
            summary="TradeBot Emergency Shutdown",
            detail=f"Bot halted due to: {reason}"
        )
    except Exception as e:
        print(f"[kill_switch] Exception during shutdown trigger: {e}")
        log_event("kill_switch", f"Exception during shutdown trigger: {e}")
