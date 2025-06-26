# tbot_bot/runtime/main.py
# Main entrypoint for TradeBot (single systemd-launched entry).
# Launches a single unified Flask app (portal_web_main.py) for all phases,
# waits for configuration/provisioning to complete, then runs strategies.
# SPEC v045: All watcher/worker/test runner launches/flags handled ONLY here.

import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, time as dt_time, timedelta

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
START_FLAG = CONTROL_DIR / "control_start.txt"
STOP_FLAG = CONTROL_DIR / "control_stop.txt"
KILL_FLAG = CONTROL_DIR / "control_kill.txt"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"

WEB_MAIN_PATH = ROOT_DIR / "tbot_web" / "py" / "portal_web_main.py"
STATUS_BOT_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "status_bot.py"
WATCHDOG_BOT_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "watchdog_bot.py"
TBOT_RUNNER_SUPERVISOR_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "tbot_runner_supervisor.py"
INTEGRATION_TEST_RUNNER_PATH = ROOT_DIR / "tbot_bot" / "test" / "integration_test_runner.py"

MARKET_OPEN_TIME = dt_time(hour=13, minute=30)
MARKET_CLOSE_TIME = dt_time(hour=20, minute=0)

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

def safe_exit(*procs):
    for proc in procs:
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
    sys.exit(0)

def is_market_open(now_time=None):
    if TEST_MODE_FLAG.exists():
        return True
    now = now_time or datetime.utcnow()
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN_TIME <= now.time() <= MARKET_CLOSE_TIME

def wait_for_operational_phase():
    operational_phases = {
        "main", "idle", "analyzing", "monitoring", "trading", "updating"
    }
    while True:
        try:
            phase = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
            if phase in operational_phases:
                return
        except Exception:
            pass
        time.sleep(1)

def main():
    try:
        from tbot_bot.support.bootstrap_utils import is_first_bootstrap
    except ImportError:
        is_first_bootstrap = lambda: False

    # FIRST BOOTSTRAP: ONLY launch config/provisioning UI, then exit.
    if is_first_bootstrap():
        flask_proc = subprocess.Popen(["python3", str(WEB_MAIN_PATH)], stdout=None, stderr=None)
        flask_proc.wait()
        sys.exit(0)

    # Launch Flask UI always in background for main UI access.
    flask_proc = subprocess.Popen(["python3", str(WEB_MAIN_PATH)], stdout=None, stderr=None)
    wait_for_operational_phase()

    # Watcher/worker/test runner processes.
    status_proc = None
    watchdog_proc = None
    supervisor_proc = None
    test_proc = None

    def is_proc_alive(proc):
        return proc is not None and proc.poll() is None

    try:
        from tbot_bot.config.env_bot import get_bot_config
        from tbot_bot.strategy.strategy_router import run_strategy
        from tbot_bot.enhancements.build_check import run_build_check
        from tbot_bot.config.error_handler_bot import handle as handle_error
        from tbot_bot.support.utils_log import log_event, get_log_settings
        from tbot_bot.runtime.status_bot import update_bot_state
        from tbot_bot.support.path_resolver import resolve_universe_cache_path

        config = get_bot_config()
        DEBUG_LOG_LEVEL, ENABLE_LOGGING, LOG_FORMAT = get_log_settings()
        DISABLE_ALL_TRADES = config.get("DISABLE_ALL_TRADES", False)
        SLEEP_TIME_STR = config.get("SLEEP_TIME", "1s")
        STRATEGY_SEQUENCE = config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")
        STRATEGY_OVERRIDE = config.get("STRATEGY_OVERRIDE")
        SLEEP_TIME = parse_sleep_time(SLEEP_TIME_STR)

        run_build_check()

        while True:
            # TEST_MODE: launch integration_test_runner.py and suspend all watchers/workers
            if TEST_MODE_FLAG.exists():
                if not test_proc or not is_proc_alive(test_proc):
                    test_proc = subprocess.Popen(
                        ["python3", str(INTEGRATION_TEST_RUNNER_PATH)],
                        stdout=None, stderr=None
                    )
                    # Terminate any watchers if running
                    for proc in [status_proc, watchdog_proc, supervisor_proc]:
                        if is_proc_alive(proc):
                            proc.terminate()
                    status_proc = None
                    watchdog_proc = None
                    supervisor_proc = None
                time.sleep(1)
                if test_proc and test_proc.poll() is not None and not TEST_MODE_FLAG.exists():
                    test_proc = None
                continue

            # Only one integration_test_runner instance active, wait if running
            if test_proc and is_proc_alive(test_proc):
                time.sleep(1)
                continue

            # Launch watchers/workers (never from other scripts)
            if not status_proc or not is_proc_alive(status_proc):
                status_proc = subprocess.Popen(["python3", str(STATUS_BOT_PATH)], stdout=None, stderr=None)
            if not watchdog_proc or not is_proc_alive(watchdog_proc):
                watchdog_proc = subprocess.Popen(["python3", str(WATCHDOG_BOT_PATH)], stdout=None, stderr=None)
            if Path(TBOT_RUNNER_SUPERVISOR_PATH).exists() and (not supervisor_proc or not is_proc_alive(supervisor_proc)):
                supervisor_proc = subprocess.Popen(["python3", str(TBOT_RUNNER_SUPERVISOR_PATH)], stdout=None, stderr=None)

            if KILL_FLAG.exists():
                safe_exit(status_proc, watchdog_proc, supervisor_proc, flask_proc, test_proc)

            now_dt = datetime.utcnow()
            strategies = [STRATEGY_OVERRIDE] if STRATEGY_OVERRIDE else STRATEGY_SEQUENCE

            for strat_name in strategies:
                strat_name = strat_name.strip().lower()
                if KILL_FLAG.exists():
                    safe_exit(status_proc, watchdog_proc, supervisor_proc, flask_proc, test_proc)

                if not is_market_open(now_dt) and not STRATEGY_OVERRIDE and not TEST_MODE_FLAG.exists():
                    update_bot_state(state="idle")
                    time.sleep(SLEEP_TIME)
                    continue

                if DISABLE_ALL_TRADES and not TEST_MODE_FLAG.exists():
                    continue

                update_bot_state(state="trading", strategy=strat_name)
                run_strategy(override=strat_name)
                update_bot_state(state="monitoring", strategy=strat_name)
                time.sleep(SLEEP_TIME)

                if STOP_FLAG.exists():
                    safe_exit(status_proc, watchdog_proc, supervisor_proc, flask_proc, test_proc)

            update_bot_state(state="idle")
            time.sleep(SLEEP_TIME)

    except Exception as e:
        try:
            from tbot_bot.config.error_handler_bot import handle as handle_error
            handle_error(e, strategy_name="main", broker="n/a", category="LogicError")
        except Exception:
            pass
    finally:
        safe_exit(status_proc, watchdog_proc, supervisor_proc, flask_proc, test_proc)

if __name__ == "__main__":
    main()
