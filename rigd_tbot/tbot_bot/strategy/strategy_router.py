# tbot_bot/strategy/strategy_router.py
# Routes execution to correct strategy based on UTC time

import time
from datetime import datetime, time as dt_time
from tbot_bot.strategy.strategy_meta import StrategyResult
from tbot_bot.strategy.strategy_open import run_open_strategy
from tbot_bot.strategy.strategy_mid import run_mid_strategy
from tbot_bot.strategy.strategy_close import run_close_strategy
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event

config = get_bot_config()

STRATEGY_SEQUENCE = [s.strip().lower() for s in config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")]
STRAT_OPEN_ENABLED = config.get("STRAT_OPEN_ENABLED", True)
STRAT_MID_ENABLED = config.get("STRAT_MID_ENABLED", True)
STRAT_CLOSE_ENABLED = config.get("STRAT_CLOSE_ENABLED", True)

def parse_start_time(tstr):
    try:
        h, m = map(int, tstr.strip().split(":"))
        return dt_time(hour=h, minute=m)
    except Exception:
        raise ValueError(f"Invalid time format: {tstr}")

START_TIME_OPEN = parse_start_time(config.get("START_TIME_OPEN", "14:30"))
START_TIME_MID = parse_start_time(config.get("START_TIME_MID", "15:30"))
START_TIME_CLOSE = parse_start_time(config.get("START_TIME_CLOSE", "19:30"))

SLEEP_TIME_STR = config.get("SLEEP_TIME", "1s")
def parse_sleep_time(sleep_str):
    if sleep_str.endswith("s"):
        return float(sleep_str[:-1])
    elif sleep_str.endswith("ms"):
        return float(sleep_str[:-2]) / 1000.0
    else:
        return float(sleep_str)

SLEEP_TIME = parse_sleep_time(SLEEP_TIME_STR)

def route_strategy(current_utc_time=None, override: str = None) -> StrategyResult:
    """
    Main router to select and execute strategy based on UTC time or manual override.
    """
    now = current_utc_time or utc_now().time()

    if override:
        log_event("router", f"Manual strategy override: {override}")
        return execute_strategy(override.strip().lower())

    for s in STRATEGY_SEQUENCE:
        if s == "open" and STRAT_OPEN_ENABLED and now >= START_TIME_OPEN:
            return execute_strategy("open")
        elif s == "mid" and STRAT_MID_ENABLED and now >= START_TIME_MID:
            return execute_strategy("mid")
        elif s == "close" and STRAT_CLOSE_ENABLED and now >= START_TIME_CLOSE:
            return execute_strategy("close")

    time.sleep(SLEEP_TIME)
    return StrategyResult(skipped=True)

def execute_strategy(name: str) -> StrategyResult:
    """
    Dispatches control to the selected strategy module.
    """
    n = name.strip().lower()
    try:
        log_event("router", f"Executing strategy: {n}")
        if n == "open":
            return run_open_strategy()
        elif n == "mid":
            return run_mid_strategy()
        elif n == "close":
            return run_close_strategy()
        else:
            raise ValueError(f"Unknown strategy: {n}")
    except Exception as e:
        log_event("router", f"Error executing {n}: {e}")
        return StrategyResult(skipped=True, errors=[str(e)])

# Entry point alias
run_strategy = route_strategy