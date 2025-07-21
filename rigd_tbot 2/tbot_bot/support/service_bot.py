# tbot_bot/support/service_bot.py
# Daemon listener for start/stop signals (optional systemd hook)
"""
service_bot.py – Optional daemon/worker mode for long-running bot processes.
Intended for systemd, supervisor, or other job schedulers to launch the bot.
"""

import time
import subprocess
from pathlib import Path
from tbot_bot.support.utils_time import utc_now         # UPDATED: from utils_time
from tbot_bot.support.utils_log import log_event    # UPDATED: from utils_log

# Path to bot runtime entry
MAIN_BOT_PATH = Path(__file__).resolve().parents[1] / "runtime" / "main.py"

def start_service_loop():
    # Import here to defer config load until after bootstrap
    from tbot_bot.config.env_bot import get_bot_config

    try:
        config = get_bot_config()
    except Exception as e:
        log_event("service_bot", f"Could not load bot config: {e}", level="error")
        return

    STRATEGY_SEQUENCE = config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")
    DISABLE_ALL_TRADES = config.get("DISABLE_ALL_TRADES", False)
    BUILD_MODE = config.get("BUILD_MODE", "debug")
    TRADING_DAYS = config.get("TRADING_DAYS", "mon,tue,wed,thu,fri").lower().split(",")

    log_event("service_bot", f"Starting TradeBot service (BUILD_MODE={BUILD_MODE})")

    while True:
        now = utc_now()
        weekday = now.strftime("%a").lower()

        if weekday not in TRADING_DAYS:
            log_event("service_bot", f"Today is {weekday.upper()} – not in TRADING_DAYS. Sleeping.")
            time.sleep(60)
            continue

        if DISABLE_ALL_TRADES:
            log_event("service_bot", "DISABLE_ALL_TRADES is set. Skipping execution.")
            time.sleep(60)
            continue

        for strategy in STRATEGY_SEQUENCE:
            strategy = strategy.strip().lower()
            if strategy not in ("open", "mid", "close"):
                continue

            try:
                log_event("service_bot", f"Invoking strategy: {strategy}")
                result = subprocess.run(
                    ["python3", str(MAIN_BOT_PATH), "--strategy", strategy],
                    capture_output=True,
                    text=True,
                    check=True
                )
                log_event("service_bot", f"[{strategy}] stdout:\n{result.stdout.strip()}")
                if result.stderr:
                    log_event("service_bot", f"[{strategy}] stderr:\n{result.stderr.strip()}", level="error")
            except subprocess.CalledProcessError as e:
                log_event("service_bot", f"Strategy {strategy} failed: {e.stderr or str(e)}", level="error")

            time.sleep(5)

        log_event("service_bot", "Strategy cycle complete. Sleeping...")
        time.sleep(60)

if __name__ == "__main__":
    try:
        start_service_loop()
    except KeyboardInterrupt:
        log_event("service_bot", "Shutdown signal received (KeyboardInterrupt)")
    except Exception as e:
        log_event("service_bot", f"Fatal error in service loop: {e}", level="error")
