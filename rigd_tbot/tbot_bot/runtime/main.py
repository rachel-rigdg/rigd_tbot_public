# tbot_bot/runtime/main.py
# Main entrypoint for TradeBot (single systemd-launched entry).
# Launches a single unified Flask app (portal_web_main.py) for all phases,
# waits for configuration/provisioning to complete, then launches tbot_supervisor.py.

import os
import sys
import subprocess
from pathlib import Path
import datetime
import socket
import time

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
WEB_MAIN_PATH = ROOT_DIR / "tbot_web" / "py" / "portal_web_main.py"
TBOT_SUPERVISOR_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "tbot_supervisor.py"

WEB_PORT = int(os.environ.get("TBOT_WEB_PORT", "6900"))
WEB_HOST = os.environ.get("TBOT_WEB_HOST", "127.0.0.1")
WAIT_OPS_SECS = int(os.environ.get("TBOT_WAIT_OPS_SECS", "90"))  # normal wait
WAIT_BOOTSTRAP_SECS = int(os.environ.get("TBOT_WAIT_BOOTSTRAP_SECS", "120"))  # first-boot longer wait (30m)

def _port_occupied(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False

def write_system_log(message):
    from tbot_bot.support.path_resolver import get_output_path
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = f"{timestamp} [main.py] {message}\n"
    try:
        log_path = get_output_path(category="logs", filename="main_bot.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[main.py][ERROR][write_system_log] {e}", flush=True)

def write_start_log():
    from tbot_bot.support.path_resolver import get_output_path
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = f"{timestamp} [main.py] BOT_START\n"
    try:
        log_path = get_output_path(category="logs", filename="start_log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[main.py][ERROR][write_start_log] {e}", flush=True)

def write_stop_log():
    from tbot_bot.support.path_resolver import get_output_path
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = f"{timestamp} [main.py] BOT_STOP\n"
    try:
        log_path = get_output_path(category="logs", filename="stop_log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[main.py][ERROR][write_stop_log] {e}", flush=True)

def _wait_for_operational_phase(deadline_epoch: float) -> bool:
    """
    Waits until bot_state.txt reports an operational phase or until deadline.
    Returns True if we observed an operational phase; False on timeout.
    Never raises.
    """
    operational_phases = {
        "running", "idle", "analyzing", "monitoring", "trading", "updating", "stopped",
        "graceful_closing_positions", "emergency_closing_positions"
    }
    write_system_log("Waiting for bot_state.txt to reach operational phase...")
    print("[main.py] Waiting for bot_state.txt to reach operational phase...", flush=True)
    last_logged = 0
    while time.time() < deadline_epoch:
        try:
            if BOT_STATE_PATH.exists():
                phase = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
                if time.time() - last_logged > 5:
                    write_system_log(f"[wait_for_operational_phase] Current phase: {phase}")
                    last_logged = time.time()
                if phase in operational_phases:
                    write_system_log(f"[wait_for_operational_phase] Entered operational phase: {phase}")
                    print(f"[main.py] Entered operational phase: {phase}", flush=True)
                    return True
        except Exception as e:
            if time.time() - last_logged > 5:
                write_system_log(f"[wait_for_operational_phase] Exception: {e}")
                last_logged = time.time()
        time.sleep(1)

    write_system_log(f"[wait_for_operational_phase] Timeout after {int(deadline_epoch - (time.time() - 0))}s; proceeding anyway.")
    print(f"[main.py] Operational phase wait timed out; proceeding.", flush=True)
    return False

def main():
    # Determine if this looks like the first bootstrap (provisioning not completed yet).
    try:
        from tbot_bot.support.bootstrap_utils import is_first_bootstrap
        first_bootstrap = bool(is_first_bootstrap())
    except Exception:
        print("[main.py][WARN] bootstrap_utils unavailable; assuming not first bootstrap.", flush=True)
        first_bootstrap = False

    write_start_log()

    # Ensure the web UI is up (or reuse an existing one).
    flask_proc = None
    if _port_occupied(WEB_HOST, WEB_PORT):
        msg = f"Web already running on {WEB_HOST}:{WEB_PORT}; skipping UI launch."
        print(f"[main.py] {msg}", flush=True)
        write_system_log(msg)
    else:
        phase_msg = " (bootstrap configuration mode)" if first_bootstrap else ""
        write_system_log("Launching unified Flask app (portal_web_main.py)..." + phase_msg)
        print("[main.py] Launching unified Flask app (portal_web_main.py)..." + phase_msg, flush=True)
        try:
            flask_proc = subprocess.Popen(
                ["python3", str(WEB_MAIN_PATH)],
                stdout=None,
                stderr=None
            )
            write_system_log(f"portal_web_main.py started with PID {flask_proc.pid}")
            print(f"[main.py] portal_web_main.py started with PID {flask_proc.pid}", flush=True)
        except Exception as e:
            write_system_log(f"Failed to launch portal_web_main.py: {e}; proceeding to supervisor.")
            print(f"[main.py] Failed to launch UI: {e}. Proceeding.", flush=True)
            flask_proc = None

    # Wait for operational state:
    # - First bootstrap: wait longer to allow provisioning to complete.
    # - Normal path: brief wait (can be tuned with TBOT_WAIT_OPS_SECS).
    wait_secs = WAIT_BOOTSTRAP_SECS if first_bootstrap else WAIT_OPS_SECS
    deadline = time.time() + max(0, wait_secs)
    _ = _wait_for_operational_phase(deadline_epoch=deadline)

    # Launch tbot_supervisor.py (single persistent process manager) — ALWAYS.
    write_system_log("Launching tbot_supervisor.py (phase/process supervisor)...")
    print("[main.py] Launching tbot_supervisor.py (phase/process supervisor)...", flush=True)
    supervisor_proc = None
    try:
        supervisor_proc = subprocess.Popen(
            ["python3", str(TBOT_SUPERVISOR_PATH)],
            stdout=None,
            stderr=None
        )
        write_system_log(f"tbot_supervisor.py started with PID {supervisor_proc.pid}")
        print(f"[main.py] tbot_supervisor.py started with PID {supervisor_proc.pid}", flush=True)
    except Exception as e:
        write_system_log(f"ERROR launching tbot_supervisor.py: {e}")
        print(f"[main.py] ERROR launching tbot_supervisor.py: {e}", flush=True)

    # Block on whichever we actually started.
    try:
        if flask_proc is not None:
            flask_proc.wait()
        elif supervisor_proc is not None:
            supervisor_proc.wait()
        else:
            while True:
                time.sleep(60)
    except KeyboardInterrupt:
        write_system_log("KeyboardInterrupt received, terminating child processes...")
        print("[main.py] KeyboardInterrupt received, terminating child processes...", flush=True)
    finally:
        try:
            if flask_proc is not None:
                write_system_log("Terminating Flask process...")
                print("[main.py] Terminating Flask process...", flush=True)
                flask_proc.terminate()
        except Exception as ex3:
            write_system_log(f"Exception terminating Flask process: {ex3}")
        try:
            if supervisor_proc is not None:
                write_system_log("Terminating supervisor process...")
                print("[main.py] Terminating supervisor process...", flush=True)
                supervisor_proc.terminate()
        except Exception as ex4:
            write_system_log(f"Exception terminating supervisor process: {ex4}")
        write_stop_log()

if __name__ == "__main__":
    main()
