# tbot_web/py/test_web.py
# Dedicated TEST_MODE UI/backend: triggers per-test flags, streams real-time logs/status, auto-resets on completion (admin-only)
import os
import threading
import time
import json
import glob
from pathlib import Path
import subprocess
from flask import Blueprint, render_template, request, jsonify, redirect, url_for

from tbot_web.support.utils_web import admin_required
from tbot_bot.support.path_resolver import (
    resolve_control_path,
    get_output_path,
    get_project_root,
)
from tbot_bot.support.bot_state_manager import set_state, get_state  # ADDED

CONTROL_DIR = resolve_control_path()
PROJECT_ROOT = get_project_root()
LOCK = threading.Lock()

test_web = Blueprint("test_web", __name__, template_folder="../templates")

# ---------- paths ----------
def get_test_log_path() -> str:
    return get_output_path("logs", "test_mode.log")

def get_test_status_path() -> str:
    return get_output_path("logs", "test_status.json")

def _ensure_logs_dir():
    lp = get_test_log_path()
    sp = get_test_status_path()
    os.makedirs(os.path.dirname(lp), exist_ok=True)
    os.makedirs(os.path.dirname(sp), exist_ok=True)

# ---------- flags ----------
def get_test_flag_path(test_name: str = None) -> Path:
    if test_name:
        return CONTROL_DIR / f"test_mode_{test_name}.flag"
    return CONTROL_DIR / "test_mode.flag"

def is_test_active(test_name: str = None) -> bool:
    return get_test_flag_path(test_name).exists()

def any_test_active() -> bool:
    if is_test_active():
        return True
    for flag in CONTROL_DIR.glob("test_mode_*.flag"):
        if flag.is_file():
            return True
    return False

def create_test_flag(test_name: str = None):
    flag_path = get_test_flag_path(test_name)
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    with open(flag_path, "w", encoding="utf-8") as f:
        f.write("1\n")

def remove_test_flag(test_name: str = None):
    flag_path = get_test_flag_path(test_name)
    if flag_path.exists():
        flag_path.unlink()

# ---------- status & logs ----------
def read_test_logs() -> str:
    log_path = get_test_log_path()
    if not os.path.exists(log_path):
        return ""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[-50000:]  # larger slice to catch module output
    except Exception:
        return ""

def get_test_status() -> dict:
    status_path = get_test_status_path()
    if not os.path.exists(status_path):
        return {}
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def set_test_status(test_status: dict):
    _ensure_logs_dir()
    status_path = get_test_status_path()
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(test_status, f, indent=2)

def update_test_status(test_name: str, status: str):
    st = get_test_status()
    st[test_name] = status
    set_test_status(st)

def reset_all_status(status_dict=None):
    if status_dict is None:
        status_dict = {}
    set_test_status(status_dict)

# ---------- env ----------
def patch_env_from_dotenv():
    env_path = Path(PROJECT_ROOT) / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # optional
    except Exception:
        # If python-dotenv isn't installed, just skip quietly
        return
    load_dotenv(dotenv_path=str(env_path), override=True)
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v
    except Exception:
        pass

# ---------- background helpers ----------
def _wait_and_finalize_generic(proc: subprocess.Popen):
    """Wait on the integration test runner; then clean the global flag & finalize ambiguous statuses."""
    proc.wait()
    # If any tests still marked QUEUED/RUNNING, set based on return code
    st = get_test_status()
    default_status = "PASSED" if proc.returncode == 0 else "ERRORS"
    updated = False
    for k, v in list(st.items()):
        if v in ("QUEUED", "RUNNING"):
            st[k] = default_status
            updated = True
    if updated:
        set_test_status(st)
    remove_test_flag(None)

def _write_subprocess_log(proc: subprocess.Popen, log_file_path: str):
    """Stream both stdout and stderr to a single log file to avoid deadlocks and keep one canonical log."""
    with open(log_file_path, "a", encoding="utf-8", errors="replace") as logf:
        while True:
            out = proc.stdout.readline() if proc.stdout else b""
            err = proc.stderr.readline() if proc.stderr else b""
            if not out and not err and proc.poll() is not None:
                break
            if out:
                try:
                    logf.write(out.decode(errors="replace"))
                except Exception:
                    logf.write(str(out))
                logf.flush()
            if err:
                try:
                    logf.write(err.decode(errors="replace"))
                except Exception:
                    logf.write(str(err))
                logf.flush()

def wait_and_update_status(test_name: str, proc: subprocess.Popen, start_size: int = 0):
    """Per-test watcher: decide status by return code; fallback to log heuristic if needed."""
    update_test_status(test_name, "RUNNING")
    proc.wait()
    status = "PASSED" if proc.returncode == 0 else "ERRORS"

    # Fallback heuristic only if return code is 0 but logs show obvious failure markers since this run
    if status == "PASSED":
        logs = ""
        log_path = get_test_log_path()
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(min(start_size, os.path.getsize(log_path)))
                logs = f.read()
        except Exception:
            logs = read_test_logs()
        if any(s in logs for s in ("FAILED", "FAIL: ", "ERROR", "Traceback")):
            status = "ERRORS"

    update_test_status(test_name, status)
    remove_test_flag(test_name)

def _launch_integration_runner():
    """Start the integration test runner subprocess (shared by /trigger and /start)."""
    patch_env_from_dotenv()
    _ensure_logs_dir()
    # If no status preset, default to all queued
    st = get_test_status() or {t: "QUEUED" for t in ALL_TESTS}
    set_test_status(st)
    create_test_flag()
    log_path = get_test_log_path()
    logf = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        ["python3", "-u", "-m", "tbot_bot.test.integration_test_runner"],
        stdout=logf,
        stderr=logf,
        bufsize=1,
        close_fds=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)},
    )
    threading.Thread(target=_wait_and_finalize_generic, args=(proc,), daemon=True).start()
    return proc

# ---------- routes ----------
@test_web.route("/", methods=["GET"])
@admin_required
def test_page():
    logs = read_test_logs()
    return render_template(
        "test.html",
        test_active=any_test_active(),
        test_status=get_test_status(),
        test_logs=logs,
        all_tests=ALL_TESTS
    )

# Full, current canonical test list for UI and backend (must match UI)
ALL_TESTS = [
    "integration_test_runner",
    "backtest_engine",
    "broker_sync",
    "broker_trade_stub",
    "coa_consistency",
    "coa_mapping",
    "coa_web_endpoints",
    "env_bot",
    "fallback_logic",
    "holdings_manager",
    "holdings_web_endpoints",
    "ledger_coa_edit",
    "ledger_concurrency",
    "ledger_corruption",
    "ledger_double_entry",
    "ledger_migration",
    "ledger_reconciliation",
    "ledger_schema",
    "ledger_write_failure",
    "logging_format",
    "main_bot",
    "mapping_upsert",
    "opening_balance",
    "screener_credentials",
    "screener_integration",
    "screener_random",
    "strategy_selfcheck",
    "strategy_tuner",
    "symbol_universe_refresh",
    "universe_cache",
]

@test_web.route("/trigger", methods=["POST"])
@admin_required
def trigger_test_mode():
    with LOCK:
        if any_test_active():
            return jsonify({"result": "already_running"})
        # initialize all to QUEUED explicitly for UI
        set_test_status({t: "QUEUED" for t in ALL_TESTS})
        _launch_integration_runner()
    return jsonify({"result": "started"})

@test_web.route("/run/<test_name>", methods=["POST"])
@admin_required
def run_individual_test(test_name):
    with LOCK:
        if any_test_active():
            return jsonify({"result": "already_running"})
        patch_env_from_dotenv()
        _ensure_logs_dir()

        test_map = {
            "integration_test_runner": "tbot_bot.test.integration_test_runner",
            "backtest_engine": "tbot_bot.test.test_backtest_engine",
            "broker_sync": "tbot_bot.test.test_broker_sync",
            "broker_trade_stub": "tbot_bot.test.test_broker_trade_stub",
            "coa_consistency": "tbot_bot.test.test_coa_consistency",
            "coa_mapping": "tbot_bot.test.test_coa_mapping",
            "coa_web_endpoints": "tbot_bot.test.test_coa_web_endpoints",
            "env_bot": "tbot_bot.test.test_env_bot",
            "fallback_logic": "tbot_bot.test.test_fallback_logic",
            "holdings_manager": "tbot_bot.test.test_holdings_manager",
            "holdings_web_endpoints": "tbot_bot.test.test_holdings_web_endpoints",
            "ledger_coa_edit": "tbot_bot.test.test_ledger_coa_edit",
            "ledger_concurrency": "tbot_bot.test.test_ledger_concurrency",
            "ledger_corruption": "tbot_bot.test.test_ledger_corruption",
            "ledger_double_entry": "tbot_bot.test.test_ledger_double_entry",
            "ledger_migration": "tbot_bot.test.test_ledger_migration",
            "ledger_reconciliation": "tbot_bot.test.test_ledger_reconciliation",
            "ledger_schema": "tbot_bot.test.test_ledger_schema",
            "ledger_write_failure": "tbot_bot.test.test_ledger_write_failure",
            "logging_format": "tbot_bot.test.test_logging_format",
            "main_bot": "tbot_bot.test.test_main_bot",
            "mapping_upsert": "tbot_bot.test.test_mapping_upsert",
            "opening_balance": "tbot_bot.test.test_opening_balance",
            "screener_credentials": "tbot_bot.test.test_screener_credentials",
            "screener_integration": "tbot_bot.test.test_screener_integration",
            "screener_random": "tbot_bot.test.test_screener_random",
            "strategy_selfcheck": "tbot_bot.test.test_strategy_selfcheck",
            "strategy_tuner": "tbot_bot.test.test_strategy_tuner",
            "symbol_universe_refresh": "tbot_bot.test.test_symbol_universe_refresh",
            "universe_cache": "tbot_bot.test.test_universe_cache",
        }
        module = test_map.get(test_name)
        if not module:
            return jsonify({"result": "unknown_test"})

        # Initialize status: mark requested test RUNNING, others QUEUED
        status_dict = {t: "QUEUED" for t in ALL_TESTS}
        status_dict[test_name] = "RUNNING"
        set_test_status(status_dict)

        create_test_flag(test_name)
        log_path = get_test_log_path()
        start_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0

        proc = subprocess.Popen(
            ["python3", "-u", "-m", module],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            close_fds=True,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)},
        )
        threading.Thread(target=_write_subprocess_log, args=(proc, log_path), daemon=True).start()
        threading.Thread(target=wait_and_update_status, args=(test_name, proc, start_size), daemon=True).start()
    return jsonify({"result": "started", "test": test_name})

@test_web.route("/logs", methods=["GET"])
@admin_required
def get_test_logs():
    logs = read_test_logs()
    status = get_test_status()
    return jsonify({"logs": logs, "status": status})

@test_web.route("/test_status", methods=["GET"])
@admin_required
def get_test_status_endpoint():
    return jsonify(get_test_status())

# ---------- NEW: Clear & Start routes ----------
@test_web.route("/clear", methods=["POST"])
@admin_required
def clear_test_mode():
    """Remove all test_mode*.flag files and reset bot_state to 'idle' so strategies can run."""
    # Remove flags
    for fp in glob.glob(str(CONTROL_DIR / "test_mode*.flag")):
        try:
            os.remove(fp)
        except FileNotFoundError:
            pass
        except Exception:
            pass
    # Reset bot_state to 'idle' via manager (no direct file writes)
    try:
        set_state("idle", reason="test:clear")
    except Exception:
        # Best-effort; swallow errors to keep UI responsive
        pass
    return redirect(url_for("status_web.status_page"))

@test_web.route("/start", methods=["POST"])
@admin_required
def start_tests():
    """Write the appropriate test flag and kick the integration test runner immediately."""
    scope = (request.form.get("scope") or "").strip().lower()
    with LOCK:
        if any_test_active():
            # Tests already running; just bounce back to tests page
            return redirect(url_for("test_web.test_page"))
        # Write flag per scope
        if scope in {"", "all"}:
            create_test_flag(None)
            # Set all tests to QUEUED for UI clarity
            set_test_status({t: "QUEUED" for t in ALL_TESTS})
        else:
            create_test_flag(scope)
            # Mark a single test RUNNING, others QUEUED (best-effort if scope matches)
            st = {t: "QUEUED" for t in ALL_TESTS}
            if scope in st:
                st[scope] = "RUNNING"
            set_test_status(st)
        # Launch the runner (handles end-of-run cleanup)
        _launch_integration_runner()
    return redirect(url_for("test_web.test_page"))

# Optional safety: clears stale flags if someone leaves UI open forever
def auto_reset_test_flag():
    for _ in range(60):
        if not any_test_active():
            return
        time.sleep(2)
    if (CONTROL_DIR / "test_mode.flag").exists():
        (CONTROL_DIR / "test_mode.flag").unlink()
    for flag in CONTROL_DIR.glob("test_mode_*.flag"):
        flag.unlink()
