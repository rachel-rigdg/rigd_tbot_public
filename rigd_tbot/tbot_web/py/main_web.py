# tbot_web/py/main_web.py

from flask import Blueprint, redirect, url_for, render_template, session, request, jsonify
from tbot_bot.support.bootstrap_utils import is_first_bootstrap
from ..support.default_config_loader import get_default_config
from tbot_web.support.auth_web import user_exists
from pathlib import Path

main_blueprint = Blueprint("main", __name__)
BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

PHASE1_STATES = ("initialize", "provisioning", "bootstrapping")
PHASE2_STATE = "registration"

def get_current_bot_state():
    try:
        with open(BOT_STATE_PATH, "r", encoding="utf-8") as f:
            state = f.read().strip()
            return state
    except Exception:
        return "unknown"

@main_blueprint.route("/", methods=["GET"])
def root_router():
    if is_first_bootstrap():
        config = get_default_config()
        session.clear()
        return redirect(url_for("login_web.login"))

    state = get_current_bot_state()

    if state in PHASE1_STATES:
        return render_template("wait.html", bot_state=state)

    if session.get("trigger_provisioning"):
        return render_template("wait.html", bot_state=state)

    if state in ("error", "shutdown_triggered"):
        return render_template("wait.html", bot_state=state)

    if state == PHASE2_STATE:
        return redirect(url_for("register_web.register_page"))

    if not user_exists():
        return redirect(url_for("register_web.register_page"))

    return render_template("main.html", bot_state=state)

@main_blueprint.route("/provisioning", methods=["GET"])
def provisioning_route():
    session.pop("trigger_provisioning", None)
    state = get_current_bot_state()
    if state in PHASE1_STATES:
        return render_template("wait.html", bot_state=state)
    return redirect(url_for("main.root_router"))

@main_blueprint.route("/main", methods=["GET"])
def main_page():
    if is_first_bootstrap():
        config = get_default_config()
        session.clear()
        return redirect(url_for("login_web.login"))
    state = get_current_bot_state()
    if state in PHASE1_STATES:
        return render_template("wait.html", bot_state=state)
    if state == PHASE2_STATE:
        return redirect(url_for("register_web.register_page"))
    if not user_exists():
        return redirect(url_for("register_web.register_page"))
    return render_template("main.html", bot_state=state)

@main_blueprint.route("/main/state", methods=["GET"])
def main_state():
    try:
        state = get_current_bot_state()
        return jsonify({"bot_state": state})
    except Exception:
        return jsonify({"bot_state": "error"}), 500
