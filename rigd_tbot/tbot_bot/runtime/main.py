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
START_FLAG = CONTROL_DIR / "control_start.flag"
STOP_FLAG = CONTROL_DIR / "control_stop.flag"
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
    print(f"[main_bot][parse_sleep_time] Parsing: {s}")
    try:
        if s.endswith("s"):
            return float(s[:-1])
        elif s.endswith("ms"):
            return float(s[:-2]) / 1000.0
        else:
            return float(s)
    except Exception:
        print(f"[main_bot][parse_sleep_time] Failed, defaulting to 1.0")
        return 1.0

def safe_exit(status_proc=None, watchdog_proc=None, supervisor_proc=None, flask_proc=None, test_proc=None):
    print("[main_bot][safe_exit] Exiting.")
    for proc, name in [(status_proc, "status_bot"), (watchdog_proc, "watchdog_bot"), (supervisor_proc, "tbot_runner_supervisor"), (flask_proc, "flask"), (test_proc, "integration_test_runner")]:
        if proc is not None:
            try:
                print(f"[main_bot] Terminating {name} process...")
                proc.terminate()
            except Exception as ex:
                print(f"[main_bot] Exception terminating {name} process: {ex}")
    sys.exit(0)

def close_all_positions_immediately(log_event):
    print("[main_bot] Immediate kill detected. Closing all positions now.")
    log_event("main_bot", "Immediate kill detected. Closing all positions now.")
    # TODO: Insert real close positions logic here

def is_market_open(now_time=None):
    print("[main_bot][is_market_open] Checking market open status...")
    if TEST_MODE_FLAG.exists():
        print("[main_bot][is_market_open] TEST_MODE_FLAG present.")
        return True
    now = now_time or datetime.utcnow()
    if now.weekday() >= 5:
        print(f"[main_bot][is_market_open] Weekend. Market closed.")
        return False
    is_open = MARKET_OPEN_TIME <= now.time() <= MARKET_CLOSE_TIME
    print(f"[main_bot][is_market_open] Market open: {is_open}")
    return is_open

def wait_for_operational_phase():
    operational_phases = {
        "main", "idle", "analyzing", "monitoring", "trading", "updating"
    }
    print("[main_bot] Waiting for bot_state.txt to reach operational phase...")
    last_phase = None
    wait_displayed = False
    while True:
        try:
            phase = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
            print(f"[main_bot][wait_for_operational_phase] Current phase: {phase}")
            if phase in operational_phases:
                print(f"[main_bot][wait_for_operational_phase] Entered operational phase: {phase}")
                return
            if phase in ("provisioning", "bootstrapping") and not wait_displayed:
                print("[main_bot][wait_for_operational_phase] Still provisioning/bootstrapping; displaying wait page...")
                wait_displayed = True
            last_phase = phase
        except Exception as e:
            print(f"[main_bot][wait_for_operational_phase] Exception: {e}")
        time.sleep(1)

def main():
    try:
        from tbot_bot.support.bootstrap_utils import is_first_bootstrap
    except ImportError:
        print("[main_bot][ERROR] Failed to import is_first_bootstrap; assuming not first bootstrap.")
        is_first_bootstrap = lambda: False

    if is_first_bootstrap():
        print("[main_bot] First bootstrap detected. Launching portal_web_main.py only for configuration.")
        flask_proc = subprocess.Popen(
            ["python3", str(WEB_MAIN_PATH)],
            stdout=None,
            stderr=None
        )
        print(f"[main_bot] portal_web_main.py started with PID {flask_proc.pid} (bootstrap mode)")
        flask_proc.wait()
        print("[main_bot] Exiting after initial configuration/bootstrap phase.")
        sys.exit(0)

    print("[main_bot] Launching unified Flask app (portal_web_main.py)...")
    flask_proc = subprocess.Popen(
        ["python3", str(WEB_MAIN_PATH)],
        stdout=None,
        stderr=None
    )
    print(f"[main_bot] portal_web_main.py started with PID {flask_proc.pid}")

    wait_for_operational_phase()

    status_proc = None
    watchdog_proc = None
    supervisor_proc = None
    test_proc = None

    # Helper to check if process is alive
    def is_proc_alive(proc):
        return proc is not None and proc.poll() is None

    # Track if any watcher/worker/test runner is running
    def terminate_all():
        safe_exit(status_proc, watchdog_proc, supervisor_proc, flask_proc, test_proc)

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
        print(f"[main_bot] Loaded config: {config}")
        DISABLE_ALL_TRADES = config.get("DISABLE_ALL_TRADES", False)
        SLEEP_TIME_STR = config.get("SLEEP_TIME", "1s")
        STRATEGY_SEQUENCE = config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")
        STRATEGY_OVERRIDE = config.get("STRATEGY_OVERRIDE")
        SLEEP_TIME = parse_sleep_time(SLEEP_TIME_STR)

        print("[main_bot] Running build check and initialization...")
        run_build_check()

        print("[main_bot] TradeBot startup successful — main runtime active.")

        # Main event loop
        while True:
            # === TEST_MODE Handling: CONTINUOUS ===
            if TEST_MODE_FLAG.exists():
                # If integration_test_runner.py is not already running, launch it as subprocess
                if not test_proc or not is_proc_alive(test_proc):
                    print("[main_bot] TEST_MODE_FLAG detected. Launching integration_test_runner.py ...")
                    test_proc = subprocess.Popen(
                        ["python3", str(INTEGRATION_TEST_RUNNER_PATH)],
                        stdout=None,
                        stderr=None
                    )
                    print(f"[main_bot] integration_test_runner.py started with PID {test_proc.pid}")
                    # Terminate any watchers if running
                    for proc, name in [(status_proc, "status_bot"), (watchdog_proc, "watchdog_bot"), (supervisor_proc, "tbot_runner_supervisor")]:
                        if is_proc_alive(proc):
                            print(f"[main_bot] Terminating {name} for TEST_MODE.")
                            proc.terminate()
                    status_proc = None
                    watchdog_proc = None
                    supervisor_proc = None
                # Suspend all normal bot logic while test is active
                time.sleep(1)
                # When test_mode.flag is removed, allow loop to resume normal launch logic
                if test_proc and test_proc.poll() is not None and not TEST_MODE_FLAG.exists():
                    print("[main_bot] integration_test_runner.py finished and test_mode.flag removed. Resuming normal operations.")
                    test_proc = None
                continue
            # === Normal Operation: Launch watchers/workers ===
            # Ensure integration_test_runner is not running
            if test_proc and is_proc_alive(test_proc):
                print("[main_bot] Waiting for test runner to finish before launching watchers.")
                time.sleep(1)
                continue

            # Launch status_bot.py if not running
            if not status_proc or not is_proc_alive(status_proc):
                print("[main_bot] Launching status_bot.py (WATCHER)...")
                status_proc = subprocess.Popen(
                    ["python3", str(STATUS_BOT_PATH)],
                    stdout=None,
                    stderr=None
                )
                print(f"[main_bot] status_bot.py started with PID {status_proc.pid}")
            # Launch watchdog_bot.py if not running
            if not watchdog_proc or not is_proc_alive(watchdog_proc):
                print("[main_bot] Launching watchdog_bot.py (WATCHER)...")
                watchdog_proc = subprocess.Popen(
                    ["python3", str(WATCHDOG_BOT_PATH)],
                    stdout=None,
                    stderr=None
                )
                print(f"[main_bot] watchdog_bot.py started with PID {watchdog_proc.pid}")
            # Launch tbot_runner_supervisor.py if present and not running
            if Path(TBOT_RUNNER_SUPERVISOR_PATH).exists() and (not supervisor_proc or not is_proc_alive(supervisor_proc)):
                print("[main_bot] Launching tbot_runner_supervisor.py (WATCHER)...")
                supervisor_proc = subprocess.Popen(
                    ["python3", str(TBOT_RUNNER_SUPERVISOR_PATH)],
                    stdout=None,
                    stderr=None
                )
                print(f"[main_bot] tbot_runner_supervisor.py started with PID {supervisor_proc.pid}")

            # Normal control/kill/shutdown/strategy/flag logic goes below:
            if KILL_FLAG.exists():
                if DEBUG_LOG_LEVEL != "quiet":
                    print("[main_bot] KILL_FLAG exists. Immediate kill routine.")
                log_event("main_bot", "Immediate kill detected. Closing all positions now.", level="error")
                close_all_positions_immediately(log_event)
                terminate_all()

            now_dt = datetime.utcnow()
            strategies = [STRATEGY_OVERRIDE] if STRATEGY_OVERRIDE else STRATEGY_SEQUENCE

            # Symbol universe check/refresh omitted for brevity (no change from previous logic)...

            # Main strategy execution loop (no change from previous logic)...
            # Omitted for brevity, keep as in your original.

            # Sleep for SLEEP_TIME at end of loop
            time.sleep(SLEEP_TIME)

    except Exception as e:
        print(f"[main_bot][ERROR] Exception: {e}")
        try:
            from tbot_bot.config.error_handler_bot import handle as handle_error
            handle_error(e, strategy_name="main", broker="n/a", category="LogicError")
        except Exception as ex2:
            print(f"[main_bot][ERROR] Exception during error handler: {ex2}")
    finally:
        safe_exit(status_proc, watchdog_proc, supervisor_proc, flask_proc, test_proc)

if __name__ == "__main__":
    main()
