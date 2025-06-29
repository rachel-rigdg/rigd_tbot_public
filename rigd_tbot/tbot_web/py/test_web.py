# tbot_web/py/test_web.py
# Dedicated TEST_MODE UI/backend: triggers per-test flags, streams real-time logs/status, auto-resets on completion (admin-only)

import os
import threading
import time
from flask import Blueprint, render_template, request, jsonify
from tbot_web.support.utils_web import admin_required
from pathlib import Path
import subprocess

CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"
TEST_LOG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / "logs" / "test_mode.log"
LOCK = threading.Lock()

test_web = Blueprint("test_web", __name__, template_folder="../templates")

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
    if not TEST_LOG_PATH.exists():
        return ""
    with open(TEST_LOG_PATH, "r", encoding="utf-8") as f:
        return f.read()[-30000:]

def get_test_status():
    if not any_test_active():
        return "idle"
    if TEST_LOG_PATH.exists():
        with open(TEST_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if lines:
                if "TEST_MODE completed" in lines[-1]:
                    return "completed"
                if "error" in lines[-1].lower():
                    return "error"
        return "running"
    return "triggered"

def create_test_flag(test_name: str = None):
    flag_path = get_test_flag_path(test_name)
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    with open(flag_path, "w") as f:
        f.write("1\n")

def remove_test_flag(test_name: str = None):
    flag_path = get_test_flag_path(test_name)
    if flag_path.exists():
        flag_path.unlink()

@test_web.route("/test/", methods=["GET"])
@admin_required
def test_page():
    status = get_test_status()
    logs = read_test_logs()
    return render_template("test.html", test_active=any_test_active(), test_status=status, test_logs=logs)

@test_web.route("/test/trigger", methods=["POST"])
@admin_required
def trigger_test_mode():
    with LOCK:
        if any_test_active():
            return jsonify({"result": "already_running"})
        create_test_flag()
        subprocess.Popen(["python3", "-m", "tbot_bot.test.integration_test_runner"])
    return jsonify({"result": "started"})

@test_web.route("/test/run/<test_name>", methods=["POST"])
@admin_required
def run_individual_test(test_name):
    with LOCK:
        if any_test_active():
            return jsonify({"result": "already_running"})
        test_map = {
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
            "logging_format": "tbot_bot.test.test_logging_format"
        }
        module = test_map.get(test_name)
        if not module:
            return jsonify({"result": "unknown_test"})
        create_test_flag(test_name)
        subprocess.Popen(["python3", "-m", module])
    return jsonify({"result": "started", "test": test_name})

@test_web.route("/test/logs", methods=["GET"])
@admin_required
def get_test_logs():
    logs = read_test_logs()
    status = get_test_status()
    return jsonify({"logs": logs, "status": status})

def auto_reset_test_flag():
    for _ in range(60):
        if not any_test_active():
            return
        time.sleep(2)
    if (CONTROL_DIR / "test_mode.flag").exists():
        (CONTROL_DIR / "test_mode.flag").unlink()
    for flag in CONTROL_DIR.glob("test_mode_*.flag"):
        flag.unlink()
