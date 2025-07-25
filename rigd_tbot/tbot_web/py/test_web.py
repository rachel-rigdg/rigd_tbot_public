# tbot_web/py/test_web.py
# Dedicated TEST_MODE UI/backend: triggers per-test flags, streams real-time logs/status, auto-resets on completion (admin-only)
import os
import threading
import time
import json
from flask import Blueprint, render_template, request, jsonify, send_file
from tbot_web.support.utils_web import admin_required
from pathlib import Path
import subprocess
from tbot_bot.support.path_resolver import (
    resolve_control_path,
    get_output_path,
    get_project_root,
)

CONTROL_DIR = resolve_control_path()
PROJECT_ROOT = get_project_root()
LOCK = threading.Lock()

test_web = Blueprint("test_web", __name__, template_folder="../templates")

def get_test_log_path():
    return get_output_path("logs", "test_mode.log")

def get_test_status_path():
    return get_output_path("logs", "test_status.json")

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

def read_test_logs():
    log_path = get_test_log_path()
    if not os.path.exists(log_path):
        return ""
    with open(log_path, "r", encoding="utf-8") as f:
        return f.read()[-30000:]

def get_test_status():
    status_path = get_test_status_path()
    if not os.path.exists(status_path):
        return {}
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def set_test_status(test_status):
    status_path = get_test_status_path()
    os.makedirs(os.path.dirname(status_path), exist_ok=True)
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(test_status, f, indent=2)

def update_test_status(test_name, status):
    st = get_test_status()
    st[test_name] = status
    set_test_status(st)

def reset_all_status(status_dict=None):
    if status_dict is None:
        status_dict = {}
    set_test_status(status_dict)

def create_test_flag(test_name: str = None):
    flag_path = get_test_flag_path(test_name)
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    with open(flag_path, "w") as f:
        f.write("1\n")

def remove_test_flag(test_name: str = None):
    flag_path = get_test_flag_path(test_name)
    if flag_path.exists():
        flag_path.unlink()

# List of all test names (UI will use this order)
ALL_TESTS = [
    "broker_sync", 
    "coa_mapping",   
    "universe_cache",
    "strategy_selfcheck",
    "screener_random",
    "screener_integration",
    "main_bot",
    "ledger_schema",
    "env_bot",
    "coa_web_endpoints",
    "coa_consistency",
    "broker_trade_stub",
    "backtest_engine",
    "logging_format",
    "fallback_logic",
    "holdings_manager"
]

def patch_env_from_dotenv():
    # Always load and export all .env values into os.environ (for subprocess consistency)
    env_path = Path(PROJECT_ROOT) / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(env_path), override=True)
        with open(env_path, "r") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v

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

@test_web.route("/trigger", methods=["POST"])
@admin_required
def trigger_test_mode():
    with LOCK:
        if any_test_active():
            return jsonify({"result": "already_running"})
        patch_env_from_dotenv()
        set_test_status({t: "QUEUED" for t in ALL_TESTS})
        create_test_flag()
        log_path = get_test_log_path()
        proc = None
        with open(log_path, "a") as log_file:
            proc = subprocess.Popen(
                ["python3", "-u", "-m", "tbot_bot.test.integration_test_runner"],
                stdout=log_file,
                stderr=log_file,
                bufsize=1,
                close_fds=True,
                cwd=str(PROJECT_ROOT),
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)},
            )
        # No background watcher needed: integration_test_runner will update statuses per test
    return jsonify({"result": "started"})

@test_web.route("/run/<test_name>", methods=["POST"])
@admin_required
def run_individual_test(test_name):
    with LOCK:
        if any_test_active():
            return jsonify({"result": "already_running"})
        patch_env_from_dotenv()
        test_map = {
            "broker_sync": "tbot_bot.test.test_broker_sync",
            "coa_mapping": "tbot_bot.test.test_coa_mapping",
            "universe_cache": "tbot_bot.test.test_universe_cache",
            "strategy_selfcheck": "tbot_bot.test.test_strategy_selfcheck",
            "screener_random": "tbot_bot.test.test_screener_random",
            "screener_integration": "tbot_bot.test.test_screener_integration",
            "main_bot": "tbot_bot.test.test_main_bot",
            "ledger_schema": "tbot_bot.test.test_ledger_schema",
            "env_bot": "tbot_bot.test.test_env_bot",
            "coa_web_endpoints": "tbot_bot.test.test_coa_web_endpoints",
            "coa_consistency": "tbot_bot.test.test_coa_consistency",
            "broker_trade_stub": "tbot_bot.test.test_broker_trade_stub",
            "backtest_engine": "tbot_bot.test.test_backtest_engine",
            "logging_format": "tbot_bot.test.test_logging_format",
            "fallback_logic": "tbot_bot.test.strategies.test_fallback_logic",
            "holdings_manager": "tbot_bot.test.test_holdings_manager"
        }
        module = test_map.get(test_name)
        if not module:
            return jsonify({"result": "unknown_test"})
        status_dict = {t: "QUEUED" for t in ALL_TESTS}
        status_dict[test_name] = "RUNNING"
        set_test_status(status_dict)
        create_test_flag(test_name)
        log_path = get_test_log_path()
        proc = None
        with open(log_path, "a") as log_file:
            proc = subprocess.Popen(
                ["python3", "-u", "-m", module],
                stdout=log_file,
                stderr=log_file,
                bufsize=1,
                close_fds=True,
                cwd=str(PROJECT_ROOT),
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)},
            )
        threading.Thread(target=wait_and_update_status, args=(test_name, proc)).start()
    return jsonify({"result": "started", "test": test_name})

def wait_and_update_status(test_name, proc):
    update_test_status(test_name, "RUNNING")
    proc.wait()
    logs = read_test_logs()
    status = "PASSED"
    if "FAILED" in logs or "FAIL" in logs or "ERROR" in logs or "Traceback" in logs:
        status = "ERRORS"
    update_test_status(test_name, status)
    remove_test_flag(test_name)

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

def auto_reset_test_flag():
    for _ in range(60):
        if not any_test_active():
            return
        time.sleep(2)
    if (CONTROL_DIR / "test_mode.flag").exists():
        (CONTROL_DIR / "test_mode.flag").unlink()
    for flag in CONTROL_DIR.glob("test_mode_*.flag"):
        flag.unlink()
