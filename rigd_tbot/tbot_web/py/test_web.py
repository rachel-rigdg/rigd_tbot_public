# tbot_web/py/test_web.py
# Dedicated TEST_MODE UI/backend: triggers test_mode.flag, streams real-time logs/status, auto-resets on completion (admin-only)

import os
import threading
import time
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from tbot_web.support.utils_web import admin_required
from pathlib import Path

TEST_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode.flag"
TEST_LOG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / "test_logs" / "test_mode.log"
LOCK = threading.Lock()

test_web = Blueprint("test_web", __name__, template_folder="../templates")

def is_test_active():
    return TEST_FLAG_PATH.exists()

def read_test_logs():
    if not TEST_LOG_PATH.exists():
        return ""
    with open(TEST_LOG_PATH, "r", encoding="utf-8") as f:
        return f.read()[-30000:]

def get_test_status():
    if not is_test_active():
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

def create_test_flag():
    TEST_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TEST_FLAG_PATH, "w") as f:
        f.write("1\n")

def remove_test_flag():
    if TEST_FLAG_PATH.exists():
        TEST_FLAG_PATH.unlink()

@test_web.route("/", methods=["GET"])
@admin_required
def test_page():
    status = get_test_status()
    logs = read_test_logs()
    return render_template("test.html", test_active=is_test_active(), test_status=status, test_logs=logs)

@test_web.route("/trigger", methods=["POST"])
@admin_required
def trigger_test_mode():
    with LOCK:
        if is_test_active():
            return jsonify({"result": "already_running"})
        create_test_flag()
    return jsonify({"result": "started"})

@test_web.route("/logs", methods=["GET"])
@admin_required
def get_test_logs():
    logs = read_test_logs()
    status = get_test_status()
    return jsonify({"logs": logs, "status": status})

def auto_reset_test_flag():
    for _ in range(60):
        if not is_test_active():
            return
        time.sleep(2)
    remove_test_flag()
