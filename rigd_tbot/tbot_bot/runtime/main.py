# tbot_bot/runtime/main.py
# Main entrypoint for TradeBot (single systemd-launched entry).
# Launches a single unified Flask app (portal_web_main.py) for UI,
# performs build checks/env decrypt/identity snapshot, updates bot_state,
# waits briefly for provisioning, and exits. NO scheduling or supervisor launch here.

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
    operational_phases = {
        "idle",
        "analyzing",
        "trading",
        "monitoring",
        "updating",
        "graceful_closing_positions",
        "shutdown_triggered",
    }
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

    write_system_log(f"[wait_for_operational_phase] Timeout afte...{int(deadline_epoch - (time.time() - 0))}s; proceeding anyway.")
    print(f"[main.py] Operational phase wait timed out; proceeding.", flush=True)
    return False

def _write_bot_state(state: str) -> None:
    try:
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        BOT_STATE_PATH.write_text(state.strip() + "\n", encoding="utf-8")
    except Exception as e:
        write_system_log(f"[write_bot_state] failed: {e}")

def _run_build_checks_and_env_decrypt() -> None:
    """Best-effort: run build checks and decrypt env, but never crash main."""
    try:
        try:
            from tbot_bot.support.build_check import run_build_check
            run_build_check()
            write_system_log("build_check: OK")
        except Exception as e:
            write_system_log(f"build_check: ERROR: {e}")
        try:
            from tbot_bot.security.security_bot import load_and_cache_env
            load_and_cache_env()
            write_system_log("env_decrypt: OK")
        except Exception as e:
            write_system_log(f"env_decrypt: ERROR: {e}")
        try:
            from tbot_bot.support.utils_identity import write_identity_snapshot
            write_identity_snapshot()
            write_system_log("identity_snapshot: OK")
        except Exception as e:
            write_system_log(f"identity_snapshot: ERROR: {e}")
    except Exception as ex:
        write_system_log(f"_run_build_checks_and_env_decrypt: unexpected error: {ex}")

def main():
    # Determine if this looks like the first bootstrap (provisioning not completed yet).
    try:
        from tbot_bot.support.bootstrap_utils import is_first_bootstrap
        first_bootstrap = bool(is_first_bootstrap())
    except Exception:
        print("[main.py][WARN] bootstrap_utils unavailable; assuming not first bootstrap.", flush=True)
        first_bootstrap = False

    # Write start, set analyzing
    write_start_log()
    _write_bot_state("analyzing")

    # Build checks, env decrypt, identity snapshot
    _run_build_checks_and_env_decrypt()

    # Optional Web UI
    flask_proc = None
    try:
        if _port_occupied(WEB_HOST, WEB_PORT):
            msg = f"Web already running on {WEB_HOST}:{WEB_PORT}; skipping UI launch."
            print(f"[main.py] {msg}", flush=True)
            write_system_log(msg)
        else:
            write_system_log("Launching unified Flask app (portal_web_main.py)...")
            print("[main.py] Launching unified Flask app (portal_web_main.py)...", flush=True)
            flask_proc = subprocess.Popen(
                ["python3", str(WEB_MAIN_PATH)],
                stdout=None,
                stderr=None
            )
            write_system_log(f"portal_web_main.py started with PID {flask_proc.pid}")
            print(f"[main.py] portal_web_main.py started with PID {flask_proc.pid}", flush=True)
    except Exception as e:
        write_system_log(f"Failed to launch portal_web_main.py: {e}")
        print(f"[main.py] Failed to launch UI: {e}", flush=True)

    # Allow provisioning window then exit; NO scheduling here.
    wait_secs = WAIT_BOOTSTRAP_SECS if first_bootstrap else WAIT_OPS_SECS
    deadline = time.time() + max(0, wait_secs)
    _ = _wait_for_operational_phase(deadline_epoch=deadline)

    _write_bot_state("idle")
    write_system_log("Exiting main.py (no scheduling; supervisor is timer-driven).")
    write_stop_log()
    # Do not manage/terminate web process here; this entrypoint exits cleanly.

if __name__ == "__main__":
    main()
