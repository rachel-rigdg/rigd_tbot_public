# tbot_web/py/start_stop_web.py
# Writes control_start.txt / control_stop.txt / control_kill.txt to signal bot lifecycle

import os
from flask import Blueprint, redirect, url_for
from tbot_web.py.login_web import login_required  # Corrected import per directory spec
from tbot_web.py.bootstrap_utils import is_first_bootstrap  # Use utility module for bootstrap check
from pathlib import Path

start_stop_blueprint = Blueprint("start_stop", __name__)

# Define control directory and flag files
BASE_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = Path(os.getenv("CONTROL_DIR", BASE_DIR / "tbot_bot" / "control"))
START_FLAG = CONTROL_DIR / "control_start.txt"
STOP_FLAG = CONTROL_DIR / "control_stop.txt"
KILL_FLAG = CONTROL_DIR / "control_kill.txt"

# Ensure control directory exists
os.makedirs(CONTROL_DIR, exist_ok=True)

@start_stop_blueprint.route("/start", methods=["POST"])
@login_required
def trigger_start():
    """
    Writes control_start.txt to signal bot start and deletes stop/kill flags if they exist.
    """
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    if STOP_FLAG.exists():
        STOP_FLAG.unlink()
    if KILL_FLAG.exists():
        KILL_FLAG.unlink()
    with open(START_FLAG, "w", encoding="utf-8") as f:
        f.write("start")
    return redirect(url_for("main.main_page"))

@start_stop_blueprint.route("/stop", methods=["POST"])
@login_required
def trigger_stop():
    """
    Writes control_stop.txt to signal bot shutdown and deletes start/kill flags if they exist.
    """
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    if START_FLAG.exists():
        START_FLAG.unlink()
    if KILL_FLAG.exists():
        KILL_FLAG.unlink()
    with open(STOP_FLAG, "w", encoding="utf-8") as f:
        f.write("stop")
    return redirect(url_for("main.main_page"))

@start_stop_blueprint.route("/kill", methods=["POST"])
@login_required
def trigger_kill():
    """
    Writes control_kill.txt to signal immediate bot shutdown and deletes start/stop flags if they exist.
    Only writes kill flag if explicitly requested by POST to this route.
    """
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    if START_FLAG.exists():
        START_FLAG.unlink()
    if STOP_FLAG.exists():
        STOP_FLAG.unlink()
    with open(KILL_FLAG, "w", encoding="utf-8") as f:
        f.write("kill")
    return redirect(url_for("main.main_page"))
