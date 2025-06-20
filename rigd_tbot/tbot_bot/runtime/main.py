# tbot_bot/runtime/main.py
# Main entrypoint for TradeBot (single systemd-launched entry).
# Launches a single unified Flask app (portal_web_main.py) for all phases, 
# waits for configuration/provisioning to complete, then runs strategies.

import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, time as dt_time

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
START_FLAG = CONTROL_DIR / "control_start.txt"
STOP_FLAG = CONTROL_DIR / "control_stop.txt"
KILL_FLAG = CONTROL_DIR / "control_kill.txt"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"

WEB_MAIN_PATH = ROOT_DIR / "tbot_web" / "py" / "portal_web_main.py"
STATUS_BOT_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "status_bot.py"

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

def safe_exit(status_proc=None):
    print("[main_bot][safe_exit] Exiting.")
    if status_proc is not None:
        try:
            print("[main_bot] Terminating status_bot process...")
            status_proc.terminate()
        except Exception as ex:
            print(f"[main_bot] Exception terminating status_bot process: {ex}")
    sys.exit(0)

def close_all_positions_immediately(log_event):
    print("[main_bot] Immediate kill detected. Closing all positions now.")
    log_event("main_bot", "Immediate kill detected. Closing all positions now.")
    # TODO: Insert real close positions logic here

def is_market_open(now_time=None, TEST_MODE_FLAG=None):
    print("[main_bot][is_market_open] Checking market open status...")
    if TEST_MODE_FLAG and TEST_MODE_FLAG.exists():
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
    while True:
        try:
            phase = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
            print(f"[main_bot][wait_for_operational_phase] Current phase: {phase}")
            if phase in operational_phases:
                print(f"[main_bot][wait_for_operational_phase] Entered operational phase: {phase}")
                return
        except Exception as e:
            print(f"[main_bot][wait_for_operational_phase] Exception: {e}")
        time.sleep(1)

def refresh_status_after_provisioning():
    """
    Refreshes the bot status and starts heartbeat after provisioning/config is complete.
    """
    from tbot_bot.runtime.status_bot import bot_status, start_heartbeat
    from tbot_bot.config.env_bot import get_bot_config
    bot_status.update_config(get_bot_config())
    bot_status.save_status()
    start_heartbeat(interval=15)

def is_status_bot_running():
    import psutil
    for proc in psutil.process_iter(["cmdline"]):
        try:
            if "status_bot.py" in " ".join(proc.info["cmdline"]):
                return True
        except Exception:
            continue
    return False

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
    if not is_status_bot_running():
        print("[main_bot] Launching status_bot.py (single instance after operational phase)...")
        status_proc = subprocess.Popen(
            ["python3", str(STATUS_BOT_PATH)],
            stdout=None,
            stderr=None
        )
        print(f"[main_bot] status_bot.py started with PID {status_proc.pid}")
    else:
        print("[main_bot] status_bot.py already running. Skipping launch.")

    try:
        refresh_status_after_provisioning()
        from tbot_bot.config.env_bot import get_bot_config
        from tbot_bot.strategy.strategy_router import run_strategy
        from tbot_bot.enhancements.build_check import run_build_check
        from tbot_bot.config.error_handler_bot import handle as handle_error
        from tbot_bot.runtime.watchdog_bot import start_watchdog
        from tbot_bot.support.utils_log import log_event, get_log_settings
        from tbot_bot.runtime.status_bot import update_bot_state

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
        start_watchdog()
        update_bot_state(state="idle")

        if KILL_FLAG.exists():
            if DEBUG_LOG_LEVEL != "quiet":
                print("[main_bot] KILL_FLAG exists. Immediate kill routine.")
            log_event("main_bot", "Immediate kill detected. Closing all positions now.", level="error")
            close_all_positions_immediately(log_event)
            safe_exit(status_proc)

        if DEBUG_LOG_LEVEL != "quiet":
            print(f"[main_bot] Strategy sequence: {STRATEGY_SEQUENCE}")
        log_event("main_bot", f"Strategy sequence: {STRATEGY_SEQUENCE}")

        if DEBUG_LOG_LEVEL != "quiet":
            print("[main_bot] TradeBot startup successful — main runtime active.")
        log_event("main_bot", "TradeBot startup successful — main runtime active.")

        while True:
            if KILL_FLAG.exists():
                if DEBUG_LOG_LEVEL != "quiet":
                    print("[main_bot] KILL_FLAG exists. Immediate kill during runtime loop.")
                log_event("main_bot", "Immediate kill during runtime loop.", level="error")
                close_all_positions_immediately(log_event)
                safe_exit(status_proc)

            now_dt = datetime.utcnow()
            strategies = [STRATEGY_OVERRIDE] if STRATEGY_OVERRIDE else STRATEGY_SEQUENCE

            for strat_name in strategies:
                strat_name = strat_name.strip().lower()
                if DEBUG_LOG_LEVEL != "quiet":
                    print(f"[main_bot] Executing strategy: {strat_name}")

                if KILL_FLAG.exists():
                    if DEBUG_LOG_LEVEL != "quiet":
                        print("[main_bot] KILL_FLAG exists. Immediate kill during strategy loop.")
                    log_event("main_bot", "Immediate kill during strategy loop.", level="error")
                    close_all_positions_immediately(log_event)
                    safe_exit(status_proc)

                if TEST_MODE_FLAG.exists():
                    if DEBUG_LOG_LEVEL != "quiet":
                        print("[main_bot] TEST_MODE detected. Forcing all strategies sequentially.")
                    log_event("main_bot", "TEST_MODE active: executing all strategies sequentially")
                    run_strategy(override="open")
                    run_strategy(override="mid")
                    run_strategy(override="close")
                    try:
                        TEST_MODE_FLAG.unlink()
                        log_event("main_bot", "TEST_MODE flag cleared after test run completion")
                    except Exception as e:
                        log_event("main_bot", f"Failed to clear TEST_MODE flag: {e}")
                    break

                if not is_market_open(now_dt, TEST_MODE_FLAG) and not STRATEGY_OVERRIDE and not TEST_MODE_FLAG.exists():
                    if DEBUG_LOG_LEVEL != "quiet":
                        print(f"[main_bot] Outside market hours. Sleeping.")
                    log_event("main_bot", "Outside market hours. Sleeping.")
                    update_bot_state(state="idle")
                    time.sleep(SLEEP_TIME)
                    continue

                if DISABLE_ALL_TRADES and not TEST_MODE_FLAG.exists():
                    if DEBUG_LOG_LEVEL != "quiet":
                        print(f"[main_bot] Trading disabled. Skipping {strat_name}")
                    log_event("main_bot", f"Trading disabled. Skipping {strat_name}")
                    continue

                update_bot_state(state="trading", strategy=strat_name)
                if DEBUG_LOG_LEVEL != "quiet":
                    print(f"[main_bot] Running strategy: {strat_name}")
                run_strategy(override=strat_name)
                if DEBUG_LOG_LEVEL != "quiet":
                    print(f"[main_bot] Completed strategy: {strat_name}")
                update_bot_state(state="monitoring", strategy=strat_name)
                time.sleep(SLEEP_TIME)

                if STOP_FLAG.exists():
                    if DEBUG_LOG_LEVEL != "quiet":
                        print("[main_bot] Graceful stop detected. Will shut down after current strategy.")
                    log_event("main_bot", "Graceful stop detected. Will shut down after current strategy.")
                    safe_exit(status_proc)

            if DEBUG_LOG_LEVEL != "quiet":
                print("[main_bot] Main loop cycle complete. Waiting for next cycle.")
            update_bot_state(state="idle")
            time.sleep(SLEEP_TIME)

    except Exception as e:
        print(f"[main_bot][ERROR] Exception: {e}")
        try:
            from tbot_bot.config.error_handler_bot import handle as handle_error
            handle_error(e, strategy_name="main", broker="n/a", category="LogicError")
        except Exception as ex2:
            print(f"[main_bot][ERROR] Exception during error handler: {ex2}")
    finally:
        try:
            if 'flask_proc' in locals() and flask_proc:
                print("[main_bot] Terminating Flask process...")
                flask_proc.terminate()
        except Exception as ex3:
            print(f"[main_bot] Exception terminating Flask process: {ex3}")
        try:
            if 'status_proc' in locals() and status_proc:
                print("[main_bot] Terminating status_bot process...")
                status_proc.terminate()
        except Exception as ex4:
            print(f"[main_bot] Exception terminating status_bot process: {ex4}")

if __name__ == "__main__":
    main()
