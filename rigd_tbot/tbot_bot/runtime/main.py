# tbot_bot/runtime/main.py
# Main bot controller (analysis → trade → shutdown)

"""
Main runtime loop for TradeBot.
Loads strategy sequence and executes in order with time-based routing.
Performs environment validation and ensures readiness before trading.
"""

import time
from datetime import datetime
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.strategy.strategy_router import run_strategy
from tbot_bot.runtime.status_bot import update_bot_state, start_heartbeat
from tbot_bot.enhancements.build_check import run_build_check
from tbot_bot.config.error_handler_bot import handle as handle_error
from tbot_bot.runtime.watchdog_bot import start_watchdog
from tbot_bot.trading.kill_switch import check_daily_loss_limit

# Load and validate bot config from decrypted .env_bot.enc
config = get_bot_config()
DISABLE_ALL_TRADES = config.get("DISABLE_ALL_TRADES", False)
SLEEP_TIME_STR = config.get("SLEEP_TIME", "1s")
STRATEGY_SEQUENCE = config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")
STRATEGY_OVERRIDE = config.get("STRATEGY_OVERRIDE")

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

def main():
    try:
        # Step 1: Validate build integrity and required structure
        run_build_check()

        # Step 2: Set initial bot state to idle
        update_bot_state("idle")

        # Step 3: Launch status heartbeat and broker watchdog
        start_heartbeat()
        start_watchdog()

        # Step 4: Abort session if DAILY_LOSS_LIMIT already breached
        if check_daily_loss_limit():
            update_bot_state("shutdown_triggered")
            return

        # Step 5: Determine strategy execution order (overridden or default)
        strategies = [STRATEGY_OVERRIDE] if STRATEGY_OVERRIDE else STRATEGY_SEQUENCE
        print(f"[main_bot] Strategy sequence: {strategies}")

        # Step 6: Execute each strategy phase in sequence
        for strat_name in strategies:
            strat_name = strat_name.strip().lower()
            update_bot_state(f"analyzing_{strat_name}")

            if DISABLE_ALL_TRADES:
                print(f"[main_bot] Trading disabled. Skipping {strat_name}")
                continue

            run_strategy(override=strat_name)
            update_bot_state(f"completed_{strat_name}")
            time.sleep(SLEEP_TIME)

        # Step 7: Final shutdown state logging
        update_bot_state("shutdown")

    except Exception as e:
        # Log fatal exception via error_handler
        handle_error(e, strategy_name="main", broker="n/a", category="LogicError")

if __name__ == "__main__":
    main()
