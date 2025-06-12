# tbot_web/py/main_web.py
# Router/shell for dashboard and blueprint registration; orchestrates UI state, v041-compliant (no privileged/provisioning actions in Flask)

from flask import Blueprint, redirect, url_for, render_template, session, request, jsonify
from tbot_web.py.bootstrap_utils import is_first_bootstrap
from ..support.configuration_loader import load_encrypted_config
from ..support.default_config_loader import get_default_config
from tbot_web.support.auth_web import user_exists
from pathlib import Path

main_blueprint = Blueprint("main", __name__)
TMP_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "support" / "tmp" / "bootstrap_config.json"
BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

INITIALIZE_STATES = ("initialize", "provisioning", "bootstrapping")

def get_current_bot_state():
    try:
        with open(BOT_STATE_PATH, "r", encoding="utf-8") as f:
            state = f.read().strip()
            print(f"[DEBUG][get_current_bot_state] Read state from bot_state.txt: {state}")
            return state
    except Exception as e:
        print(f"[DEBUG][get_current_bot_state] Exception reading bot_state.txt: {e}")
        return "unknown"

@main_blueprint.route("/", methods=["GET"])
def root_router():
    print(f"[main_web] root_router called from {request.path}")
    print(f"[DEBUG][root_router] session keys at entry: {list(session.keys())}")
    print(f"[DEBUG][root_router] session trigger_provisioning at entry: {session.get('trigger_provisioning')}")
    session.pop("trigger_provisioning", None)
    print(f"[DEBUG][root_router] session keys after pop: {list(session.keys())}")
    print(f"[DEBUG][root_router] session trigger_provisioning after pop: {session.get('trigger_provisioning')}")

    state = get_current_bot_state()
    print(f"[DEBUG][root_router] bot_state: {state}")

    if state == "initialize":
        print("[main_web] State is initialize, rendering configuration.html from main_web")
        config = {}
        categories = [
            "bot_identity", "broker", "screener_api",
            "smtp", "network_config", "acct_api"
        ]
        for cat in categories:
            config.update(load_encrypted_config(cat))
        if not config:
            config = get_default_config()
        return render_template("configuration.html", config=config)

    if state in ("provisioning", "bootstrapping"):
        print(f"[main_web] State is {state}, rendering wait.html")
        return render_template("wait.html", bot_state=state)

    if session.get("trigger_provisioning"):
        print("[main_web] trigger_provisioning=True, rendering wait.html")
        return render_template("wait.html", bot_state=state)

    if state in ("error", "shutdown_triggered"):
        print(f"[main_web] ERROR or SHUTDOWN_TRIGGERED detected, rendering wait page (state={state})")
        return render_template("wait.html", bot_state=state)

    if state == "registration":
        print("[main_web] State is registration, redirecting to user registration page.")
        return redirect(url_for("register_web.register_page"))

    if not user_exists():
        print("[main_web] No users exist; redirecting to user registration page.")
        return redirect(url_for("register_web.register_page"))

    print(f"[main_web] bot state is {state}, rendering main.html")
    return render_template("main.html", bot_state=state)

@main_blueprint.route("/provisioning", methods=["GET"])
def provisioning_route():
    print(f"[main_web] provisioning_route called from {request.path}")
    print(f"[main_web] session keys: {list(session.keys())}")
    print(f"[main_web] session trigger_provisioning (before pop): {session.get('trigger_provisioning')}")
    session.pop("trigger_provisioning", None)
    print(f"[main_web] session keys (after pop): {list(session.keys())}")
    print(f"[main_web] session trigger_provisioning (after pop): {session.get('trigger_provisioning')}")
    state = get_current_bot_state()
    print(f"[DEBUG][provisioning_route] bot_state: {state}")
    return render_template("wait.html", bot_state=state)

@main_blueprint.route("/main", methods=["GET"])
def main_page():
    print(f"[main_web] main_page called from {request.path}")
    print(f"[main_web] session keys: {list(session.keys())}")
    print(f"[main_web] session trigger_provisioning: {session.get('trigger_provisioning')}")
    state = get_current_bot_state()
    print(f"[DEBUG][main_page] bot_state: {state}")
    if state in ("initialize", "provisioning", "bootstrapping"):
        print(f"[main_web] State is {state}, redirecting to root_router (configuration/wait)")
        return redirect(url_for("main.root_router"))
    if state == "registration":
        print("[main_web] State is registration, redirecting to user registration page.")
        return redirect(url_for("register_web.register_page"))
    if not user_exists():
        print("[main_web] No users exist; redirecting to user registration page.")
        return redirect(url_for("register_web.register_page"))
    return render_template("main.html", bot_state=state)

@main_blueprint.route("/main/state", methods=["GET"])
def main_state():
    try:
        state = get_current_bot_state()
        return jsonify({"state": state})
    except Exception:
        return jsonify({"state": "error"}), 500
