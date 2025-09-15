# tbot_bot/runtime/main.py
# SINGLE ENTRYPOINT (works with or without systemd).
# - Launch unified Flask app (portal_web_main.py)
# - Run build checks / env decrypt / identity snapshot
# - Self-schedule tbot_supervisor.py daily at 00:01 UTC
#   * If main.py starts after 00:01 UTC, supervisor launches immediately (once).
# - No .timer / @instance units required.
# - Clean shutdown: propagate SIGTERM/SIGINT to children.

import os
import sys
import subprocess
from pathlib import Path
import datetime as dt
import socket
import time
import signal

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
WEB_MAIN_PATH = ROOT_DIR / "tbot_web" / "py" / "portal_web_main.py"
TBOT_SUPERVISOR_PATH = ROOT_DIR / "tbot_bot" / "runtime" / "tbot_supervisor.py"

WEB_PORT = int(os.environ.get("TBOT_WEB_PORT", "6900"))
WEB_HOST = os.environ.get("TBOT_WEB_HOST", "0.0.0.0")  # default: listen on all interfaces
WAIT_OPS_SECS = int(os.environ.get("TBOT_WAIT_OPS_SECS", "90"))
WAIT_BOOTSTRAP_SECS = int(os.environ.get("TBOT_WAIT_BOOTSTRAP_SECS", "120"))
SUP_ENABLE = os.environ.get("TBOT_SUPERVISOR_ENABLE", "1") != "0"
SUP_TRIGGER_HHMM = os.environ.get("TBOT_SUPERVISOR_UTC_HHMM", "0600")  # "HHMM" in UTC
POLL_SECS = int(os.environ.get("TBOT_MAIN_POLL_SECS", "5"))

child_procs = {"flask": None, "supervisor": None}
_shutting_down = False

def _port_occupied(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False

def _utc_now():
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)

def _next_utc_trigger(now_utc: dt.datetime) -> dt.datetime:
    hh = int(SUP_TRIGGER_HHMM[:2])
    mm = int(SUP_TRIGGER_HHMM[2:])
    today = now_utc.date()
    today_trigger = dt.datetime(today.year, today.month, today.day, hh, mm, tzinfo=dt.timezone.utc)
    if now_utc <= today_trigger:
        return today_trigger
    # else tomorrow
    tomorrow = today + dt.timedelta(days=1)
    return dt.datetime(tomorrow.year, tomorrow.month, tomorrow.day, hh, mm, tzinfo=dt.timezone.utc)

def write_system_log(message):
    from tbot_bot.support.path_resolver import get_output_path
    ts = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = f"{ts} [main.py] {message}\n"
    try:
        log_path = get_output_path(category="logs", filename="main_bot.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[main.py][ERROR][write_system_log] {e}", flush=True)

def write_start_log():
    from tbot_bot.support.path_resolver import get_output_path
    ts = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        log_path = get_output_path(category="logs", filename="start_log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts} [main.py] BOT_START\n")
    except Exception as e:
        print(f"[main.py][ERROR][write_start_log] {e}", flush=True)

def write_stop_log():
    from tbot_bot.support.path_resolver import get_output_path
    ts = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        log_path = get_output_path(category="logs", filename="stop_log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts} [main.py] BOT_STOP\n")
    except Exception as e:
        print(f"[main.py][ERROR][write_stop_log] {e}", flush=True)

def _write_bot_state(state: str) -> None:
    try:
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        BOT_STATE_PATH.write_text(state.strip() + "\n", encoding="utf-8")
    except Exception as e:
        write_system_log(f"[write_bot_state] failed: {e}")

def _run_build_checks_and_env_decrypt() -> None:
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

def _launch_flask():
    if _port_occupied(WEB_HOST, WEB_PORT):
        msg = f"Web already running on {WEB_HOST}:{WEB_PORT}; skipping UI launch."
        print(f"[main.py] {msg}", flush=True)
        write_system_log(msg)
        return None
    write_system_log("Launching unified Flask app (portal_web_main.py)...")
    print("[main.py] Launching unified Flask app (portal_web_main.py)...", flush=True)
    env = os.environ.copy()
    env.setdefault("TBOT_WEB_HOST", WEB_HOST)  # ensure portal binds as requested
    env.setdefault("TBOT_WEB_PORT", str(WEB_PORT))
    proc = subprocess.Popen(
        ["python3", str(WEB_MAIN_PATH)],
        stdout=None, stderr=None, env=env
    )
    write_system_log(f"portal_web_main.py started with PID {proc.pid} ({WEB_HOST}:{WEB_PORT})")
    print(f"[main.py] portal_web_main.py started with PID {proc.pid}", flush=True)
    return proc

def _launch_supervisor():
    write_system_log("Launching tbot_supervisor.py (daily run).")
    print("[main.py] Launching tbot_supervisor.py…", flush=True)
    env = os.environ.copy()
    # If your supervisor supports args like --once, keep it simple; otherwise just run.
    try:
        proc = subprocess.Popen(["python3", str(TBOT_SUPERVISOR_PATH)], stdout=None, stderr=None, env=env)
    except FileNotFoundError:
        # Fallback to module execution if needed
        proc = subprocess.Popen([sys.executable, "-m", "tbot_bot.runtime.tbot_supervisor"], stdout=None, stderr=None, env=env)
    write_system_log(f"tbot_supervisor.py started with PID {proc.pid}")
    return proc

def _graceful_shutdown(*_args):
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    write_system_log("Shutting down…")
    # Stop children
    for name, proc in child_procs.items():
        if proc and proc.poll() is None:
            try:
                write_system_log(f"Terminating child {name} (pid {proc.pid})")
                proc.terminate()
            except Exception:
                pass
    # Give them a moment
    t0 = time.time()
    while time.time() - t0 < 8:
        if all((p is None or p.poll() is not None) for p in child_procs.values()):
            break
        time.sleep(0.25)
    # Kill if still alive
    for name, proc in child_procs.items():
        if proc and proc.poll() is None:
            try:
                write_system_log(f"Killing child {name} (pid {proc.pid})")
                proc.kill()
            except Exception:
                pass
    _write_bot_state("idle")
    write_stop_log()
    sys.exit(0)

def _wait_for_operational_phase(deadline_epoch: float) -> None:
    # Best-effort log spam control
    operational = {
        "idle","analyzing","trading","monitoring",
        "updating","graceful_closing_positions","shutdown_triggered",
        "provisioning","bootstrapping","registration",
    }
    last_logged = 0
    while time.time() < deadline_epoch:
        try:
            if BOT_STATE_PATH.exists():
                phase = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
                if time.time() - last_logged > 5:
                    write_system_log(f"[wait_for_operational_phase] Current phase: {phase}")
                    last_logged = time.time()
                if phase in operational:
                    # just keep logging; don't block on a specific target
                    pass
        except Exception as e:
            if time.time() - last_logged > 5:
                write_system_log(f"[wait_for_operational_phase] Exception: {e}")
                last_logged = time.time()
        time.sleep(1)

def main():
    # Trap signals early
    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)

    # Detect first bootstrap
    try:
        from tbot_bot.support.bootstrap_utils import is_first_bootstrap
        first_bootstrap = bool(is_first_bootstrap())
    except Exception:
        print("[main.py][WARN] bootstrap_utils unavailable; assuming not first bootstrap.", flush=True)
        first_bootstrap = False

    write_start_log()
    _write_bot_state("analyzing")
    _run_build_checks_and_env_decrypt()

    # Launch Flask UI (binds to 0.0.0.0 by default)
    child_procs["flask"] = _launch_flask()

    # Give UI/provisioning a window to settle
    wait_secs = WAIT_BOOTSTRAP_SECS if first_bootstrap else WAIT_OPS_SECS
    _wait_for_operational_phase(deadline_epoch=time.time() + max(0, wait_secs))

    # Self-schedule supervisor
    next_fire = None
    if SUP_ENABLE:
        now = _utc_now()
        target = _next_utc_trigger(now)
        if now >= target:
            # We're late -> fire immediately today
            write_system_log(f"Missed {SUP_TRIGGER_HHMM}Z window; starting supervisor now.")
            child_procs["supervisor"] = _launch_supervisor()
            # schedule next for tomorrow
            next_fire = _next_utc_trigger(_utc_now())
        else:
            next_fire = target
        write_system_log(f"Next supervisor trigger set for {next_fire.isoformat() if next_fire else 'disabled'}")
    else:
        write_system_log("Supervisor disabled by TBOT_SUPERVISOR_ENABLE=0")
        next_fire = None

    # Main loop: tick, (re)launch supervisor at window, keep main alive, watch children
    while True:
        if _shutting_down:
            time.sleep(0.2)
            continue

        now = _utc_now()
        # Relaunch Flask if it died (keep UI resilient)
        if child_procs["flask"] and child_procs["flask"].poll() is not None:
            write_system_log("Flask process died; relaunching.")
            child_procs["flask"] = _launch_flask()

        # Handle supervisor schedule
        if SUP_ENABLE:
            sup = child_procs["supervisor"]
            sup_dead = (sup is not None and sup.poll() is not None)
            if next_fire and now >= next_fire and (sup is None or sup_dead):
                child_procs["supervisor"] = _launch_supervisor()
                # Set next window to tomorrow 00:01Z
                next_fire = _next_utc_trigger(_utc_now())
                write_system_log(f"Supervisor launched; next trigger {next_fire.isoformat()}")

        time.sleep(POLL_SECS)

if __name__ == "__main__":
    main()
