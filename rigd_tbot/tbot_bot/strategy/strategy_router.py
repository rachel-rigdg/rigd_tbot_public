# tbot_bot/strategy/strategy_router.py
# Routes execution to correct strategy based on UTC time and TEST_MODE override
# THIS MODULE IS NOT A WORKER OR SUPERVISOR. IT MUST NEVER BE LAUNCHED DIRECTLY BY main.py, CLI, or as a persistent process.
# Only imported by tbot_supervisor.py, integration_test_runner.py, or strategy modules for routing logic.

import time
from datetime import datetime, time as dt_time
from tbot_bot.strategy.strategy_meta import StrategyResult
from tbot_bot.strategy.strategy_open import run_open_strategy
from tbot_bot.strategy.strategy_mid import run_mid_strategy
from tbot_bot.strategy.strategy_close import run_close_strategy
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from pathlib import Path

config = get_bot_config()

# Retrieve strategy sequence and enable/disable config values
STRATEGY_SEQUENCE = [s.strip().lower() for s in config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")]
STRAT_OPEN_ENABLED = config.get("STRAT_OPEN_ENABLED", True)
STRAT_MID_ENABLED = config.get("STRAT_MID_ENABLED", True)
STRAT_CLOSE_ENABLED = config.get("STRAT_CLOSE_ENABLED", True)

# Screener selection variables from .env_bot
SCREENER_SOURCE = config.get("SCREENER_SOURCE", "FINNHUB").strip().upper()
OPEN_SCREENER = config.get("OPEN_SCREENER", SCREENER_SOURCE).strip().upper()
MID_SCREENER = config.get("MID_SCREENER", SCREENER_SOURCE).strip().upper()
CLOSE_SCREENER = config.get("CLOSE_SCREENER", SCREENER_SOURCE).strip().upper()

# Parse strategy start times from config
def parse_start_time(tstr):
    try:
        h, m = map(int, tstr.strip().split(":"))
        return dt_time(hour=h, minute=m)
    except Exception:
        raise ValueError(f"Invalid time format: {tstr}")

START_TIME_OPEN = parse_start_time(config.get("START_TIME_OPEN", "14:30"))
START_TIME_MID = parse_start_time(config.get("START_TIME_MID", "15:30"))
START_TIME_CLOSE = parse_start_time(config.get("START_TIME_CLOSE", "19:30"))

# Check for TEST_MODE flag presence
def is_test_mode_active() -> bool:
    test_flag_path = Path(__file__).resolve().parents[2] / "control" / "test_mode.flag"
    return test_flag_path.exists()

# Symbol universe check before strategies
def ensure_universe_valid():
    from tbot_bot.screeners.screener_utils import is_cache_stale, UniverseCacheError
    from tbot_bot.screeners.universe_orchestrator import main as orchestrator_main
    try:
        if is_cache_stale():
            log_event("router", "Universe cache missing or stale. Triggering rebuild.")
            orchestrator_main()
            log_event("router", "Universe cache rebuild completed by strategy router.")
    except UniverseCacheError as ue:
        log_event("router", f"Failed to rebuild universe: {ue}")
        raise

# Helper to import screener dynamically
def get_screener_class(source_name):
    src = source_name.strip().upper()
    if src == "ALPACA":
        from tbot_bot.screeners.screeners.alpaca_screener import AlpacaScreener
        return AlpacaScreener
    elif src == "FINNHUB":
        from tbot_bot.screeners.screeners.finnhub_screener import FinnhubScreener
        return FinnhubScreener
    elif src == "IBKR":
        from tbot_bot.screeners.screeners.ibkr_screener import IBKRScreener
        return IBKRScreener
    elif src == "TRADIER":
        from tbot_bot.screeners.screeners.tradier_screener import TradierScreener
        return TradierScreener
    else:
        raise ValueError(f"Unknown screener source: {src}")

# Main strategy routing function
def route_strategy(current_utc_time=None, override: str = None) -> StrategyResult:
    """
    Main router to select and execute strategy based on UTC time, manual override,
    or TEST_MODE immediate execution bypassing schedule.
    Only to be called by supervisor, integration test, or higher-level modules.
    Never launched as a persistent worker/process.
    """
    # Ensure universe cache is valid/fresh before strategies
    ensure_universe_valid()

    # If TEST_MODE active, run all strategies sequentially immediately and once
    if is_test_mode_active():
        log_event("router", "TEST_MODE active: executing all strategies sequentially")
        results = []
        for strat, screener_name in zip(["open", "mid", "close"], [OPEN_SCREENER, MID_SCREENER, CLOSE_SCREENER]):
            try:
                log_event("router", f"TEST_MODE executing strategy: {strat} with screener: {screener_name}")
                result = execute_strategy(strat, screener_override=screener_name)
                results.append(result)
            except Exception as e:
                log_event("router", f"TEST_MODE error executing {strat}: {e}")
                results.append(StrategyResult(skipped=True, errors=[str(e)]))
        # After execution, delete test_mode.flag to reset
        try:
            test_flag_path = Path(__file__).resolve().parents[2] / "control" / "test_mode.flag"
            test_flag_path.unlink()
            log_event("router", "TEST_MODE flag cleared after test sequence completion")
        except Exception as e:
            log_event("router", f"Failed to clear TEST_MODE flag: {e}")
        # Return last strategy result or combined as needed (return last here)
        return results[-1]

    now = current_utc_time or utc_now().time()

    # Check for manual override (if provided)
    if override:
        strat_name = override.strip().lower()
        screener_override = {
            "open": OPEN_SCREENER,
            "mid": MID_SCREENER,
            "close": CLOSE_SCREENER
        }.get(strat_name, SCREENER_SOURCE)
        log_event("router", f"Manual strategy override: {override} with screener: {screener_override}")
        return execute_strategy(strat_name, screener_override=screener_override)

    # Iterate through the strategy sequence and select the strategy to execute
    for s, screener_name in zip(STRATEGY_SEQUENCE, [OPEN_SCREENER, MID_SCREENER, CLOSE_SCREENER]):
        if s == "open" and STRAT_OPEN_ENABLED and now >= START_TIME_OPEN:
            return execute_strategy("open", screener_override=OPEN_SCREENER)
        elif s == "mid" and STRAT_MID_ENABLED and now >= START_TIME_MID:
            return execute_strategy("mid", screener_override=MID_SCREENER)
        elif s == "close" and STRAT_CLOSE_ENABLED and now >= START_TIME_CLOSE:
            return execute_strategy("close", screener_override=CLOSE_SCREENER)

    return StrategyResult(skipped=True)

# Executes the selected strategy and returns the result
def execute_strategy(name: str, screener_override: str = None) -> StrategyResult:
    """
    Dispatches control to the selected strategy module, injecting screener class from .env_bot.
    """
    n = name.strip().lower()
    screener_class = get_screener_class(screener_override or SCREENER_SOURCE)
    try:
        log_event("router", f"Executing strategy: {n} with screener: {screener_class.__name__}")
        if n == "open":
            return run_open_strategy(screener_class=screener_class)
        elif n == "mid":
            return run_mid_strategy(screener_class=screener_class)
        elif n == "close":
            return run_close_strategy(screener_class=screener_class)
        else:
            raise ValueError(f"Unknown strategy: {n}")
    except Exception as e:
        log_event("router", f"Error executing {n}: {e}")
        return StrategyResult(skipped=True, errors=[str(e)])

# Entry point alias
run_strategy = route_strategy
