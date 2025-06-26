# tbot_bot/runtime/tbot_supervisor.py
# Central phase/process supervisor for TradeBot.
# Responsible for all phase transitions, persistent monitoring, and launching all watcher/worker/test runner processes.
# Only launched by main.py after successful provisioning/bootstrapping and transition to operational state.
# No watcher/worker/test runner is ever launched except by this supervisor.

import os
import sys
import time
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"
CONTROL_START_FLAG = CONTROL_DIR / "control_start.flag"
CONTROL_STOP_FLAG = CONTROL_DIR / "control_stop.flag"

STATUS_BOT_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "status_bot.py"
WATCHDOG_BOT_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "watchdog_bot.py"
# Add other watcher/worker paths here as needed

def read_bot_state():
    try:
        return BOT_STATE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""

def launch_subprocess(cmd_path):
    return subprocess.Popen(["python3", str(cmd_path)], stdout=None, stderr=None)

def ensure_singleton(process_name):
    import psutil
    for proc in psutil.process_iter(["cmdline"]):
        try:
            if process_name in " ".join(proc.info["cmdline"]):
                return True
        except Exception:
            continue
    return False

def main():
    print("[tbot_supervisor] Starting TradeBot phase supervisor.")
    processes = {}

    # Launch persistent watchers (status_bot, watchdog_bot)
    if not ensure_singleton("status_bot.py"):
        print("[tbot_supervisor] Launching status_bot.py...")
        processes["status_bot"] = launch_subprocess(STATUS_BOT_PATH)
    else:
        print("[tbot_supervisor] status_bot.py already running.")

    if not ensure_singleton("watchdog_bot.py"):
        print("[tbot_supervisor] Launching watchdog_bot.py...")
        processes["watchdog_bot"] = launch_subprocess(WATCHDOG_BOT_PATH)
    else:
        print("[tbot_supervisor] watchdog_bot.py already running.")

    # Main phase/process supervision loop
    try:
        while True:
            state = read_bot_state()
            if state in ("shutdown", "shutdown_triggered", "error"):
                print(f"[tbot_supervisor] Detected shutdown/error state: {state}. Terminating subprocesses and exiting.")
                break

            # TEST_MODE support: launch test runner if flag is present
            if TEST_MODE_FLAG.exists():
                print("[tbot_supervisor] TEST_MODE flag detected. Launching test runner...")
                TEST_RUNNER_PATH = ROOT_DIR / "tbot_bot" / "test" / "integration_test_runner.py"
                if not ensure_singleton("integration_test_runner.py"):
                    processes["test_runner"] = launch_subprocess(TEST_RUNNER_PATH)
                # Wait for test runner to finish and remove flag
                while TEST_MODE_FLAG.exists():
                    time.sleep(1)
                print("[tbot_supervisor] TEST_MODE complete. Test runner finished.")

            # Start/stop logic for control flags
            if CONTROL_START_FLAG.exists():
                # Set bot state to "started"
                BOT_STATE_PATH.write_text("started", encoding="utf-8")
                print("[tbot_supervisor] CONTROL_START_FLAG detected. Set bot state to 'started'.")
                CONTROL_START_FLAG.unlink(missing_ok=True)

            if CONTROL_STOP_FLAG.exists():
                # Set bot state to "graceful_closing_positions"
                BOT_STATE_PATH.write_text("graceful_closing_positions", encoding="utf-8")
                print("[tbot_supervisor] CONTROL_STOP_FLAG detected. Set bot state to 'graceful_closing_positions'.")
                CONTROL_STOP_FLAG.unlink(missing_ok=True)

            # TODO: Launch/monitor additional workers if required by phase

            time.sleep(2)

    except KeyboardInterrupt:
        print("[tbot_supervisor] KeyboardInterrupt received, terminating.")

    finally:
        # Terminate all launched child processes
        for pname, proc in processes.items():
            try:
                print(f"[tbot_supervisor] Terminating {pname} process...")
                proc.terminate()
            except Exception as e:
                print(f"[tbot_supervisor] Exception terminating {pname}: {e}")

if __name__ == "__main__":
    main()
