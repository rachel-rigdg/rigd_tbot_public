# tbot_bot/runtime/holdings_maintenance.py
# Schedules and triggers holdings operations post-open or per rebalance interval.

import time
from datetime import datetime, timedelta
from tbot_bot.trading.holdings_manager import perform_holdings_cycle
from tbot_bot.support.path_resolver import get_bot_state_path
from tbot_bot.support.bootstrap_utils import is_first_bootstrap
from tbot_bot.support.utils_log import get_logger

log = get_logger(__name__)

HOLDINGS_MAINTENANCE_INTERVAL = 600  # seconds (10 minutes)

def _is_bot_ready():
    if is_first_bootstrap(quiet_mode=True):
        return False
    state_path = get_bot_state_path()
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = f.read().strip()
        return state not in ("initialize", "provisioning", "bootstrapping")
    except Exception:
        return False

def main():
    log.info("Holdings maintenance scheduler started.")
    last_run = None
    while True:
        try:
            if _is_bot_ready():
                now = datetime.utcnow()
                if not last_run or (now - last_run) >= timedelta(seconds=HOLDINGS_MAINTENANCE_INTERVAL):
                    log.info("Triggering scheduled holdings maintenance cycle.")
                    perform_holdings_cycle()
                    last_run = now
        except Exception as e:
            log.error(f"Exception in holdings_maintenance: {e}")
        time.sleep(30)

if __name__ == "__main__":
    main()
