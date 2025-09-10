# tbot_bot/strategy/strategy_router.py
# Routes execution to correct strategy based on UTC time (supervisor-driven) and TEST_MODE override.
# THIS MODULE IS NOT A WORKER OR SUPERVISOR. IT MUST NEVER BE LAUNCHED DIRECTLY by main.py, CLI, or as a persistent process.
# Only called by tbot_supervisor, integration_test_runner, or tests.

from pathlib import Path
import datetime
from tbot_bot.strategy.strategy_meta import StrategyResult
from tbot_bot.config.env_bot import (
    get_bot_config,
    get_open_time_utc,
    get_mid_time_utc,
    get_close_time_utc,
)
from tbot_bot.support.utils_time import utc_now, parse_time_utc
from tbot_bot.support.utils_log import log_event

config = get_bot_config()

# Router respects enable/disable flags and declared order but does not self-schedule.
STRATEGY_SEQUENCE = [s.strip().lower() for s in config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")]
STRAT_OPEN_ENABLED = bool(config.get("STRAT_OPEN_ENABLED", True))
STRAT_MID_ENABLED = bool(config.get("STRAT_MID_ENABLED", True))
STRAT_CLOSE_ENABLED = bool(config.get("STRAT_CLOSE_ENABLED", True))

# Screener selection from .env_bot (upper-cased names resolve to concrete classes below)
SCREENER_SOURCE = str(config.get("SCREENER_SOURCE", "FINNHUB")).strip().upper()
OPEN_SCREENER = str(config.get("OPEN_SCREENER", SCREENER_SOURCE)).strip().upper()
MID_SCREENER = str(config.get("MID_SCREENER", SCREENER_SOURCE)).strip().upper()
CLOSE_SCREENER = str(config.get("CLOSE_SCREENER", SCREENER_SOURCE)).strip().upper()

CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"
TEST_FLAG_PATH = CONTROL_DIR / "test_mode.flag"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"

def _bot_state() -> str:
    try:
        return BOT_STATE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"

def is_test_mode_active() -> bool:
    return TEST_FLAG_PATH.exists()

def ensure_universe_valid():
    # Lazy import to avoid import-time side effects
    from tbot_bot.screeners.screener_utils import is_cache_stale, UniverseCacheError
    from tbot_bot.screeners.universe_orchestrator import main as orchestrator_main
    try:
        if is_cache_stale():
            print("[strategy_router] Universe cache missing/stale — triggering rebuild...", flush=True)
            log_event("router", "Universe cache missing or stale. Triggering rebuild.")
            orchestrator_main()
            print("[strategy_router] Universe cache rebuild complete.", flush=True)
            log_event("router", "Universe cache rebuild completed by strategy router.")
    except UniverseCacheError as ue:
        log_event("router", f"Failed to rebuild universe: {ue}")
        raise

def get_screener_class(source_name: str):
    # Lazy, selective imports to avoid dragging heavy deps at import-time
    src = (source_name or "").strip().upper()
    if src == "ALPACA":
        from tbot_bot.screeners.screeners.alpaca_screener import AlpacaScreener
        return AlpacaScreener
    if src == "FINNHUB":
        from tbot_bot.screeners.screeners.finnhub_screener import FinnhubScreener
        return FinnhubScreener
    if src == "IBKR":
        from tbot_bot.screeners.screeners.ibkr_screener import IBKRScreener
        return IBKRScreener
    if src == "TRADIER":
        from tbot_bot.screeners.screeners.tradier_screener import TradierScreener
        return TradierScreener
    raise ValueError(f"Unknown screener source: {src}")

def _parsed_utc_times():
    """Read UTC execution times from env getters and return as datetime.time objects."""
    open_tt = parse_time_utc(get_open_time_utc() or "13:30")
    mid_tt = parse_time_utc(get_mid_time_utc() or "16:00")
    close_tt = parse_time_utc(get_close_time_utc() or "19:45")
    return open_tt, mid_tt, close_tt

def route_strategy(current_utc_time=None, override: str = None) -> StrategyResult:
    """
    Router selects a strategy when called.
    - In TEST_MODE: runs all three sequentially (open→mid→close) once.
    - With override: dispatches the named strategy immediately.
    - Otherwise: uses UTC now vs START_TIME_* (UTC) to pick the first eligible in STRATEGY_SEQUENCE.
    The router does NOT launch processes and does NOT stamp per-day guards; supervisor owns scheduling.
    """
    state = _bot_state()
    print(f"[strategy_router] route_strategy called (override={override!r}, state={state})", flush=True)

    # Gate on bot_state for normal operation (allow TEST_MODE/override bypass)
    if not (override or is_test_mode_active()) and state != "running":
        log_event("router", f"Bot state '{state}' not runnable — skipping route.")
        print(f"[strategy_router] Skipping — bot_state='{state}' (no override/TEST_MODE).", flush=True)
        return StrategyResult(skipped=True)

    # Ensure universe cache is available/fresh
    ensure_universe_valid()

    # TEST_MODE: run all sequentially once, then clear flag
    if is_test_mode_active():
        log_event("router", "TEST_MODE active: executing open→mid→close sequentially")
        print("[strategy_router] TEST_MODE active — running OPEN→MID→CLOSE sequentially.", flush=True)
        results = []
        for strat, scr in (("open", OPEN_SCREENER), ("mid", MID_SCREENER), ("close", CLOSE_SCREENER)):
            print(f"[strategy_router] Launching {strat.upper()} (TEST_MODE) with screener={scr}", flush=True)
            results.append(execute_strategy(strat, screener_override=scr))
        try:
            TEST_FLAG_PATH.unlink()
            log_event("router", "TEST_MODE flag cleared after run.")
            print("[strategy_router] TEST_MODE flag cleared.", flush=True)
        except Exception:
            pass
        return results[-1] if results else StrategyResult(skipped=True)

    # Override: dispatch immediately (supervisor-driven path)
    if override:
        n = override.strip().lower()
        scr = {"open": OPEN_SCREENER, "mid": MID_SCREENER, "close": CLOSE_SCREENER}.get(n, SCREENER_SOURCE)
        log_event("router", f"Manual override: {n} using screener {scr}")
        print(f"[strategy_router] Launching {n.upper()} via override with screener={scr}", flush=True)
        return execute_strategy(n, screener_override=scr)

    # UTC-based selection (defensive; supervisor should normally call with override)
    now_tt = current_utc_time if isinstance(current_utc_time, datetime.time) else utc_now().time()
    open_tt, mid_tt, close_tt = _parsed_utc_times()

    seq_map = {
        "open":  (STRAT_OPEN_ENABLED,  open_tt,  OPEN_SCREENER),
        "mid":   (STRAT_MID_ENABLED,   mid_tt,   MID_SCREENER),
        "close": (STRAT_CLOSE_ENABLED, close_tt, CLOSE_SCREENER),
    }

    for name in STRATEGY_SEQUENCE:
        enabled, start_tt, scr = seq_map.get(name, (False, None, None))
        if enabled and start_tt and now_tt >= start_tt:
            print(f"[strategy_router] Time-based selection launching {name.upper()} with screener={scr}", flush=True)
            return execute_strategy(name, screener_override=scr)

    print("[strategy_router] No eligible strategy at this time — skipped.", flush=True)
    return StrategyResult(skipped=True)

def execute_strategy(name: str, screener_override: str = None) -> StrategyResult:
    """
    Dispatch to concrete strategy module, injecting screener class.
    Lazy-import strategies to avoid import-time crashes from unrelated modules.
    """
    n = (name or "").strip().lower()
    screener_class = get_screener_class(screener_override or SCREENER_SOURCE)

    try:
        if n == "open":
            from tbot_bot.strategy.strategy_open import run_open_strategy
            log_event("router", f"Executing OPEN with {screener_class.__name__}")
            print(f"[strategy_router] Executing OPEN with {screener_class.__name__}", flush=True)
            return run_open_strategy(screener_class=screener_class)

        if n == "mid":
            from tbot_bot.strategy.strategy_mid import run_mid_strategy
            log_event("router", f"Executing MID with {screener_class.__name__}")
            print(f"[strategy_router] Executing MID with {screener_class.__name__}", flush=True)
            return run_mid_strategy(screener_class=screener_class)

        if n == "close":
            from tbot_bot.strategy.strategy_close import run_close_strategy
            log_event("router", f"Executing CLOSE with {screener_class.__name__}")
            print(f"[strategy_router] Executing CLOSE with {screener_class.__name__}", flush=True)
            return run_close_strategy(screener_class=screener_class)

        raise ValueError(f"Unknown strategy: {n}")

    except Exception as e:
        log_event("router", f"Error executing {n}: {e}")
        print(f"[strategy_router] ERROR executing {n}: {e}", flush=True)
        return StrategyResult(skipped=True, errors=[str(e)])

# Entry point alias for legacy callers
run_strategy = route_strategy
