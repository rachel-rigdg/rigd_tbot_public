# tbot_web/py/start_stop_web.py
# Writes control_start.flag / control_stop.flag / control_kill.flag to signal bot lifecycle

import os
from flask import Blueprint, redirect, url_for, flash
from tbot_web.py.login_web import login_required  # keep existing import path
from tbot_bot.support.bootstrap_utils import is_first_bootstrap
from pathlib import Path
from tbot_bot.support import path_resolver
from tbot_bot.support.bot_state_manager import set_state  # ADDED

start_stop_blueprint = Blueprint("start_stop_web", __name__)

# Resolve CONTROL_DIR via path_resolver, allow ENV override
PROJECT_ROOT = path_resolver.get_project_root()  # fixed: was resolve_project_root()
CONTROL_DIR = Path(os.getenv("CONTROL_DIR", PROJECT_ROOT / "tbot_bot" / "control"))

# Flag files use .flag suffix
START_FLAG = CONTROL_DIR / "control_start.flag"
STOP_FLAG  = CONTROL_DIR / "control_stop.flag"
KILL_FLAG  = CONTROL_DIR / "control_kill.flag"

# Ensure control directory exists
CONTROL_DIR.mkdir(parents=True, exist_ok=True)


@start_stop_blueprint.route("/start", methods=["POST"])
@login_required
def trigger_start():
    """
    Writes control_start.flag to signal bot start and deletes stop/kill flags if they exist.
    POST-only.
    """
    if is_first_bootstrap():
        flash("First bootstrap not complete. Configure the bot first.", "warning")
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        STOP_FLAG.unlink(missing_ok=True)
        KILL_FLAG.unlink(missing_ok=True)
        START_FLAG.write_text("start", encoding="utf-8")
        # State: moving into live scheduling/execution flow
        set_state("running", reason="ui:start")
        flash("Start signal issued.", "success")
    except Exception as e:
        flash(f"Failed to issue start signal: {e}", "error")
    return redirect(url_for("main.main_page"))


@start_stop_blueprint.route("/stop", methods=["POST"])
@login_required
def trigger_stop():
    """
    Writes control_stop.flag to signal bot stop and deletes start/kill flags if they exist.
    POST-only.
    """
    if is_first_bootstrap():
        flash("First bootstrap not complete. Configure the bot first.", "warning")
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        START_FLAG.unlink(missing_ok=True)
        KILL_FLAG.unlink(missing_ok=True)
        STOP_FLAG.write_text("stop", encoding="utf-8")
        set_state("idle", reason="ui:stop")
        flash("Stop signal issued.", "success")
    except Exception as e:
        flash(f"Failed to issue stop signal: {e}", "error")
    return redirect(url_for("main.main_page"))


@start_stop_blueprint.route("/kill", methods=["POST"])
@login_required
def trigger_kill():
    """
    Writes control_kill.flag to request immediate shutdown and deletes start/stop flags if they exist.
    POST-only.
    """
    if is_first_bootstrap():
        flash("First bootstrap not complete. Configure the bot first.", "warning")
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        START_FLAG.unlink(missing_ok=True)
        STOP_FLAG.unlink(missing_ok=True)
        KILL_FLAG.write_text("kill", encoding="utf-8")
        set_state("idle", reason="ui:kill")
        flash("Kill signal issued.", "success")
    except Exception as e:
        flash(f"Failed to issue kill signal: {e}", "error")
    return redirect(url_for("main.main_page"))
