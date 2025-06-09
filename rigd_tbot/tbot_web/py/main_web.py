# tbot_web/py/main_web.py
# Router/shell for dashboard and blueprint registration; orchestrates UI state, v041-compliant (no privileged/provisioning actions in Flask)

from flask import Blueprint, redirect, url_for, render_template, session, request
from tbot_web.py.bootstrap_utils import is_first_bootstrap
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
    # Always clear the session flag as early as possible
    session.pop("trigger_provisioning", None)
    print(f"[DEBUG][root_router] session keys after pop: {list(session.keys())}")
    print(f"[DEBUG][root_router] session trigger_provisioning after pop: {session.get('trigger_provisioning')}")

    if is_first_bootstrap():
        print("[main_web] is_first_bootstrap=True, redirecting to configuration_web.show_configuration")
        return redirect(url_for("configuration_web.show_configuration"))

    state = get_current_bot_state()
    print(f"[DEBUG][root_router] bot_state: {state}")

    if state in INITIALIZE_STATES:
        print(f"[main_web] initialize/provisioning/bootstrapping detected, redirecting to provisioning_route (state={state})")
        return redirect(url_for("main.provisioning_route"))

    if session.get("trigger_provisioning"):
        print("[main_web] trigger_provisioning=True, redirecting to provisioning_route")
        return redirect(url_for("main.provisioning_route"))

    if state in ("error", "shutdown_triggered"):
        print(f"[main_web] ERROR or SHUTDOWN_TRIGGERED detected, rendering wait page (state={state})")
        return render_template("wait.html", bot_state=state)

    print(f"[main_web] bot state is {state}, redirecting to main_page.")
    return redirect(url_for("main.main_page"))

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
    return render_template("main.html", bot_state=state)
