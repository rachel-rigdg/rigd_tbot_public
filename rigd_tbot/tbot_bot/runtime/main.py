# tbot_bot/runtime/main.py
# Main entrypoint for TradeBot (single systemd-launched entry).
# Launches a single unified Flask app (portal_web_main.py) for all phases,
# waits for configuration/provisioning to complete, then launches tbot_supervisor.py.

import os
import sys
import subprocess
from pathlib import Path
import datetime

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
WEB_MAIN_PATH = ROOT_DIR / "tbot_web" / "py" / "portal_web_main.py"
TBOT_SUPERVISOR_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "tbot_supervisor.py"

def write_system_log(message):
    from tbot_bot.support.path_resolver import get_output_path
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = f"{timestamp} [main.py] {message}\n"
    try:
        log_path = get_output_path(category="logs", filename="main_bot.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[main.py][ERROR][write_system_log] {e}")

def write_start_log():
    from tbot_bot.support.path_resolver import get_output_path
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = f"{timestamp} [main.py] BOT_START\n"
    try:
        log_path = get_output_path(category="logs", filename="start_log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[main.py][ERROR][write_start_log] {e}")

def write_stop_log():
    from tbot_bot.support.path_resolver import get_output_path
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = f"{timestamp} [main.py] BOT_STOP\n"
    try:
        log_path = get_output_path(category="logs", filename="stop_log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[main.py][ERROR][write_stop_log] {e}")

def main():
    try:
        from tbot_bot.support.bootstrap_utils import is_first_bootstrap
    except ImportError:
        print("[main.py][ERROR] Failed to import is_first_bootstrap; assuming not first bootstrap.")
        is_first_bootstrap = lambda: False

    if is_first_bootstrap():
        write_system_log("First bootstrap detected. Launching portal_web_main.py only for configuration.")
        flask_proc = subprocess.Popen(
            ["python3", str(WEB_MAIN_PATH)],
            stdout=None,
            stderr=None
        )
        write_system_log(f"portal_web_main.py started with PID {flask_proc.pid} (bootstrap mode)")
        flask_proc.wait()
        write_system_log("Exiting after initial configuration/bootstrap phase.")
        sys.exit(0)

    write_system_log("Launching unified Flask app (portal_web_main.py)...")
    write_start_log()
    flask_proc = subprocess.Popen(
        ["python3", str(WEB_MAIN_PATH)],
        stdout=None,
        stderr=None
    )
    write_system_log(f"portal_web_main.py started with PID {flask_proc.pid}")

    # Wait for bot_state.txt to reach post-bootstrap operational phase before launching supervisor
    operational_phases = {
        "started", "idle", "analyzing", "monitoring", "trading", "updating", "stopped",
        "graceful_closing_positions", "emergency_closing_positions"
    }
    write_system_log("Waiting for bot_state.txt to reach operational phase...")
    while True:
        try:
            phase = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
            write_system_log(f"[wait_for_operational_phase] Current phase: {phase}")
            if phase in operational_phases:
                write_system_log(f"[wait_for_operational_phase] Entered operational phase: {phase}")
                break
        except Exception as e:
            write_system_log(f"[wait_for_operational_phase] Exception: {e}")
        import time
        time.sleep(1)

    # Launch tbot_supervisor.py (single persistent process manager)
    write_system_log("Launching tbot_supervisor.py (phase/process supervisor)...")
    supervisor_proc = subprocess.Popen(
        ["python3", str(TBOT_SUPERVISOR_PATH)],
        stdout=None,
        stderr=None
    )
    write_system_log(f"tbot_supervisor.py started with PID {supervisor_proc.pid}")

    try:
        flask_proc.wait()
    except KeyboardInterrupt:
        write_system_log("KeyboardInterrupt received, terminating Flask and supervisor processes...")
    finally:
        try:
            if 'flask_proc' in locals() and flask_proc:
                write_system_log("Terminating Flask process...")
                flask_proc.terminate()
        except Exception as ex3:
            write_system_log(f"Exception terminating Flask process: {ex3}")
        try:
            if 'supervisor_proc' in locals() and supervisor_proc:
                write_system_log("Terminating supervisor process...")
                supervisor_proc.terminate()
        except Exception as ex4:
            write_system_log(f"Exception terminating supervisor process: {ex4}")
        write_stop_log()

if __name__ == "__main__":
    main()
