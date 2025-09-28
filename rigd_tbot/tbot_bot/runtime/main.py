# tbot_bot/runtime/main.py
# SINGLE ENTRYPOINT (works with or without systemd).
# - Launch unified Flask app (portal_web_main.py)
# - Run build checks / env decrypt / identity snapshot
# - Self-schedule tbot_supervisor.py daily at 00:01 UTC
#   * If main.py starts after 00:01 UTC, supervisor launches immediately (once).
# - No .timer / @instance units required.
# - Clean shutdown: propagate SIGTERM/SIGINT to children.

# --- PATH BOOTSTRAP (must be first) ---
import sys, pathlib
_THIS_FILE = pathlib.Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# --- END PATH BOOTSTRAP ---

import os
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
INTEGRATION_TEST_RUNNER_MOD = "tbot_bot.test.integration_test_runner"

WEB_PORT = int(os.environ.get("TBOT_WEB_PORT", "6900"))
WEB_HOST = os.environ.get("TBOT_WEB_HOST", "0.0.0.0")  # default: listen on all interfaces
WAIT_OPS_SECS = int(os.environ.get("TBOT_WAIT_OPS_SECS", "90"))
WAIT_BOOTSTRAP_SECS = int(os.environ.get("TBOT_WAIT_BOOTSTRAP_SECS", "120"))
SUP_ENABLE = os.environ.get("TBOT_SUPERVISOR_ENABLE", "1") != "0"
SUP_TRIGGER_HHMM = os.environ.get("TBOT_SUPERVISOR_UTC_HHMM", "0001")  # "HHMM" in UTC (default 00:01)
POLL_SECS = int(os.environ.get("TBOT_MAIN_POLL_SECS", "5"))

child_procs = {"flask": None, "supervisor": None, "test_runner": None}
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

# --- NEW: ensure child procs can import repo modules without changing call style ---
def _ensure_child_has_repo_on_path(env: dict) -> None:
    """
    Prepend the repo root to PYTHONPATH for child processes only.
    Avoids modifying parent sys.path or switching to -m.
    """
    try:
        repo = str(ROOT_DIR)
        cur = env.get("PYTHONPATH", "")
        if not cur:
            env["PYTHONPATH"] = repo
        elif repo not in cur.split(os.pathsep):
            env["PYTHONPATH"] = repo + os.pathsep + cur
    except Exception:
        # Never block launch on path-set issues
        pass

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
    _ensure_child_has_repo_on_path(env)  # <-- surgical addition
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
    _ensure_child_has_repo_on_path(env)  # <-- surgical addition
    # If your supervisor supports args like --once, keep it simple; otherwise just run.
    try:
        proc = subprocess.Popen(["python3", str(TBOT_SUPERVISOR_PATH)], stdout=None, stderr=None, env=env)
    except FileNotFoundError:
        # Fallback to module execution if needed
        proc = subprocess.Popen([sys.executable, "-m", "tbot_bot.runtime.tbot_supervisor"], stdout=None, stderr=None, env=env)
    write_system_log(f"tbot_supervisor.py started with PID {proc.pid}")
    return proc

def _launch_integration_test_runner():
    """
    Start the integration test runner in TEST_MODE and keep supervisor paused.
    """
    write_system_log("TEST_MODE detected — launching integration_test_runner and suspending live schedule.")
    print("[main.py] TEST_MODE detected — launching integration_test_runner…", flush=True)
    env = os.environ.copy()
    # Ensure PYTHONPATH so -m works reliably
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONPATH", str(ROOT_DIR))
    # Ensure the global test flag exists (runner will handle inner flags & cleanup)
    (CONTROL_DIR / "test_mode.flag").write_text("1\n", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", INTEGRATION_TEST_RUNNER_MOD],
            cwd=str(ROOT_DIR),
            stdout=None,
            stderr=None,
            env=env
        )
        write_system_log(f"integration_test_runner started with PID {proc.pid}")
        return proc
    except Exception as e:
        write_system_log(f"Failed to launch integration_test_runner: {e}")
        return None

def _is_test_mode_active() -> bool:
    """
    TEST_MODE is active if a global test_mode.flag or any test_mode_*.flag exists.
    """
    if (CONTROL_DIR / "test_mode.flag").exists():
        return True
    # any individual test flag also indicates active testing
    for p in CONTROL_DIR.glob("test_mode_*.flag"):
        return True
    return False

def _ensure_no_supervisor_when_test():
    """
    If supervisor is running while TEST_MODE is active, terminate it to avoid overlap.
    """
    sup = child_procs.get("supervisor")
    if sup and sup.poll() is None:
        write_system_log("TEST_MODE active → terminating running supervisor to prevent live trades.")
        try:
            sup.terminate()
        except Exception:
            pass
        # best effort wait
        t0 = time.time()
        while time.time() - t0 < 5 and sup.poll() is None:
            time.sleep(0.2)
        if sup.poll() is None:
            try:
                sup.kill()
            except Exception:
                pass
    child_procs["supervisor"] = None

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

    # --- TEST MODE GATE (startup) -----------------------------------------
    # If test mode is active at startup, do NOT launch supervisor. Run tests instead.
    if _is_test_mode_active():
        _write_bot_state("analyzing")
        # (surgical) do NOT terminate/disable supervisor; allow schedule to run regardless
        if child_procs.get("test_runner") is None or child_procs["test_runner"].poll() is not None:
            child_procs["test_runner"] = _launch_integration_test_runner()

    # ----------------------------------------------------------------------
    # Self-schedule supervisor (and ALWAYS launch one run immediately)
    # ----------------------------------------------------------------------
    next_fire = None
    if SUP_ENABLE:
        # 1) Launch supervisor immediately on startup (unconditionally)
        write_system_log("Immediate supervisor launch on startup.")
        child_procs["supervisor"] = _launch_supervisor()

        # 2) Compute the next daily trigger so we don't double-run today
        now = _utc_now()
        today_or_next = _next_utc_trigger(now)
        # If we launched *before* today's trigger, skip today and schedule tomorrow
        if now < today_or_next:
            next_fire = _next_utc_trigger(today_or_next + dt.timedelta(minutes=1))
        else:
            # Launched at/after today's trigger → next is tomorrow's trigger
            next_fire = _next_utc_trigger(now)
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

        # -------- TEST MODE SUPERVISION -----------------------------------
        if _is_test_mode_active():
            # (surgical) no supervisor termination; just ensure test runner is active
            tr = child_procs.get("test_runner")
            if tr is None or tr.poll() is not None:
                child_procs["test_runner"] = _launch_integration_test_runner()
        else:
            # Not in TEST_MODE. If test runner had been running and finished, ensure it is cleared.
            tr = child_procs.get("test_runner")
            if tr and tr.poll() is None:
                # Runner still alive but flags cleared unexpectedly — let it finish; scheduling continues regardless.
                write_system_log("Test runner still active; live scheduling continues.")

        # Handle supervisor schedule normally
        if SUP_ENABLE:
            sup = child_procs["supervisor"]
            sup_dead = (sup is not None and sup.poll() is not None)
            if next_fire is None:
                next_fire = _next_utc_trigger(_utc_now())
                write_system_log(f"Resumed/ensured live scheduling. Next supervisor trigger {next_fire.isoformat()}")
            if next_fire and now >= next_fire and (sup is None or sup_dead):
                child_procs["supervisor"] = _launch_supervisor()
                # Set next window to tomorrow at configured time
                next_fire = _next_utc_trigger(_utc_now())
                write_system_log(f"Supervisor launched; next trigger {next_fire.isoformat()}")

        time.sleep(POLL_SECS)

if __name__ == "__main__":
    main()
