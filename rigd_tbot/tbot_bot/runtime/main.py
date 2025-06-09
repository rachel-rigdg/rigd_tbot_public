# tbot_bot/runtime/main.py
# Main bot controller (analysis → trade → shutdown)

"""
Main runtime loop for TradeBot.
Loads strategy sequence and executes in order with time-based routing.
Performs environment validation and ensures readiness before trading.
"""

import time
from datetime import datetime, time as dt_time
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.strategy.strategy_router import run_strategy
from tbot_bot.runtime.status_bot import update_bot_state, start_heartbeat
from tbot_bot.enhancements.build_check import run_build_check
from tbot_bot.config.error_handler_bot import handle as handle_error
from tbot_bot.runtime.watchdog_bot import start_watchdog
from tbot_bot.trading.kill_switch import check_daily_loss_limit
from tbot_bot.support.utils_log import log_event
from pathlib import Path
import sys
import os

# Load and validate bot config from decrypted .env_bot.enc
config = get_bot_config()
DISABLE_ALL_TRADES = config.get("DISABLE_ALL_TRADES", False)
SLEEP_TIME_STR = config.get("SLEEP_TIME", "1s")
STRATEGY_SEQUENCE = config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")
STRATEGY_OVERRIDE = config.get("STRATEGY_OVERRIDE")

CONTROL_DIR = Path(os.getenv("CONTROL_DIR", Path(__file__).resolve().parents[2] / "control"))
START_FLAG = CONTROL_DIR / "control_start.txt"
STOP_FLAG = CONTROL_DIR / "control_stop.txt"
KILL_FLAG = CONTROL_DIR / "control_kill.txt"

# Define market hours gating (UTC time)
MARKET_OPEN_TIME = dt_time(hour=13, minute=30)   # 09:30 EST in UTC
MARKET_CLOSE_TIME = dt_time(hour=20, minute=0)   # 16:00 EST in UTC

# Convert SLEEP_TIME string into float seconds
def parse_sleep_time(s):
    try:
        if s.endswith("s"):
            return float(s[:-1])
        elif s.endswith("ms"):
            return float(s[:-2]) / 1000.0
        else:
            return float(s)
    except Exception:
        return 1.0

SLEEP_TIME = parse_sleep_time(SLEEP_TIME_STR)

def safe_exit():
    # Final shutdown state logging and cleanup
    update_bot_state("shutdown")
    sys.exit(0)

def close_all_positions_immediately():
    # Placeholder for immediate close logic; integrate actual close routine here
    print("[main_bot] Immediate kill detected. Closing all positions now.")
    log_event("main_bot", "Immediate kill detected. Closing all positions now.")
    update_bot_state("emergency_closing_positions")
    # TODO: Insert real close positions logic here

def is_market_open(now_time=None):
    now = now_time or datetime.utcnow()
    if now.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    return MARKET_OPEN_TIME <= now.time() <= MARKET_CLOSE_TIME

def main():
    try:
        update_bot_state("idle")  # Bot starts in idle state
        run_build_check()
        update_bot_state("monitoring")  # Transition to monitoring once build check passes
        start_heartbeat()
        start_watchdog()

        if check_daily_loss_limit():
            update_bot_state("shutdown_triggered")  # If daily loss limit is exceeded, transition to shutdown_triggered
            return
        if KILL_FLAG.exists():
            close_all_positions_immediately()
            safe_exit()

        strategies = [STRATEGY_OVERRIDE] if STRATEGY_OVERRIDE else STRATEGY_SEQUENCE
        print(f"[main_bot] Strategy sequence: {strategies}")
        log_event("main_bot", f"Strategy sequence: {strategies}")

        print("[main_bot] TradeBot startup successful — main runtime active.")
        log_event("main_bot", "TradeBot startup successful — main runtime active.")

        graceful_stop = False

        for strat_name in strategies:
            strat_name = strat_name.strip().lower()
            update_bot_state(f"analyzing_{strat_name}")  # Bot state transitions to 'analyzing' during each strategy

            if KILL_FLAG.exists():
                close_all_positions_immediately()
                safe_exit()

            now_dt = datetime.utcnow()
            if not is_market_open(now_dt) and not STRATEGY_OVERRIDE:
                print(f"[main_bot] Outside market hours. Skipping {strat_name}.")
                log_event("main_bot", f"Outside market hours. Skipping {strat_name}.")
                continue

            if DISABLE_ALL_TRADES:
                print(f"[main_bot] Trading disabled. Skipping {strat_name}")
                log_event("main_bot", f"Trading disabled. Skipping {strat_name}")
                continue

            update_bot_state("trading", strategy=strat_name)  # Update state to 'trading' when strategy is executed
            run_strategy(override=strat_name)
            update_bot_state(f"completed_{strat_name}")  # Mark strategy as completed after execution
            time.sleep(SLEEP_TIME)

            if STOP_FLAG.exists():
                print("[main_bot] Graceful stop detected. Will shut down after current strategy.")
                log_event("main_bot", "Graceful stop detected. Will shut down after current strategy.")
                graceful_stop = True
                break

        if graceful_stop:
            print("[main_bot] Executing graceful shutdown after strategy completion. Closing positions.")
            log_event("main_bot", "Executing graceful shutdown after strategy completion. Closing positions.")
            update_bot_state("graceful_closing_positions")  # Transition to graceful closing positions state
            # TODO: Insert real close positions logic here

        update_bot_state("shutdown")  # Final bot state set to 'shutdown'

    except Exception as e:
        update_bot_state("error")  # Update bot state to 'error' if an exception occurs
        handle_error(e, strategy_name="main", broker="n/a", category="LogicError")

if __name__ == "__main__":
    main()
