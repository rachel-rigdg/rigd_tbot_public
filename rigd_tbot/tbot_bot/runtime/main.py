# tbot_bot/runtime/main.py
# Main entrypoint for TradeBot (single systemd-launched entry).
# Launches a single unified Flask app (portal_web_main.py) for all phases,
# waits for configuration/provisioning to complete, then launches tbot_supervisor.py.

import os
import sys
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
WEB_MAIN_PATH = ROOT_DIR / "tbot_web" / "py" / "portal_web_main.py"
TBOT_SUPERVISOR_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "tbot_supervisor.py"

def main():
    try:
        from tbot_bot.support.bootstrap_utils import is_first_bootstrap
    except ImportError:
        print("[main.py][ERROR] Failed to import is_first_bootstrap; assuming not first bootstrap.")
        is_first_bootstrap = lambda: False

    if is_first_bootstrap():
        print("[main.py] First bootstrap detected. Launching portal_web_main.py only for configuration.")
        flask_proc = subprocess.Popen(
            ["python3", str(WEB_MAIN_PATH)],
            stdout=None,
            stderr=None
        )
        print(f"[main.py] portal_web_main.py started with PID {flask_proc.pid} (bootstrap mode)")
        flask_proc.wait()
        print("[main.py] Exiting after initial configuration/bootstrap phase.")
        sys.exit(0)

    print("[main.py] Launching unified Flask app (portal_web_main.py)...")
    flask_proc = subprocess.Popen(
        ["python3", str(WEB_MAIN_PATH)],
        stdout=None,
        stderr=None
    )
    print(f"[main.py] portal_web_main.py started with PID {flask_proc.pid}")

    # Wait for bot_state.txt to reach post-bootstrap operational phase before launching supervisor
    operational_phases = {
        "started", "idle", "analyzing", "monitoring", "trading", "updating", "stopped",
        "graceful_closing_positions", "emergency_closing_positions"
    }
    print("[main.py] Waiting for bot_state.txt to reach operational phase...")
    while True:
        try:
            phase = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
            print(f"[main.py][wait_for_operational_phase] Current phase: {phase}")
            if phase in operational_phases:
                print(f"[main.py][wait_for_operational_phase] Entered operational phase: {phase}")
                break
        except Exception as e:
            print(f"[main.py][wait_for_operational_phase] Exception: {e}")
        import time
        time.sleep(1)

    # Launch tbot_supervisor.py (single persistent process manager)
    print("[main.py] Launching tbot_supervisor.py (phase/process supervisor)...")
    supervisor_proc = subprocess.Popen(
        ["python3", str(TBOT_SUPERVISOR_PATH)],
        stdout=None,
        stderr=None
    )
    print(f"[main.py] tbot_supervisor.py started with PID {supervisor_proc.pid}")

    try:
        flask_proc.wait()
    except KeyboardInterrupt:
        print("[main.py] KeyboardInterrupt received, terminating Flask and supervisor processes...")
    finally:
        try:
            if 'flask_proc' in locals() and flask_proc:
                print("[main.py] Terminating Flask process...")
                flask_proc.terminate()
        except Exception as ex3:
            print(f"[main.py] Exception terminating Flask process: {ex3}")
        try:
            if 'supervisor_proc' in locals() and supervisor_proc:
                print("[main.py] Terminating supervisor process...")
                supervisor_proc.terminate()
        except Exception as ex4:
            print(f"[main.py] Exception terminating supervisor process: {ex4}")

if __name__ == "__main__":
    main()
