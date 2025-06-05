# tbot_web/py/main_web.py
# Router/shell for dashboard and blueprint registration; orchestrates UI state, v041-compliant (no privileged/provisioning actions in Flask)

from flask import Blueprint, redirect, url_for, render_template, session, request
from tbot_web.py.bootstrap_utils import is_first_bootstrap
from pathlib import Path

main_blueprint = Blueprint("main", __name__)
TMP_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "support" / "tmp" / "bootstrap_config.json"

@main_blueprint.route("/", methods=["GET"])
def root_router():
    print(f"[main_web] root_router called from {request.path}")
    if is_first_bootstrap():
        print("[main_web] is_first_bootstrap=True, redirecting to configuration_web.show_configuration")
        return redirect(url_for("configuration_web.show_configuration"))
    # Always route to provisioning to check if provisioning is pending
    return redirect(url_for("main.provisioning_route"))

@main_blueprint.route("/provisioning", methods=["GET"])
def provisioning_route():
    print(f"[main_web] provisioning_route called from {request.path}")
    print(f"[main_web] session keys: {list(session.keys())}")
    print(f"[main_web] session trigger_provisioning (before pop): {session.get('trigger_provisioning')}")
    # Always show wait screen while external runner handles provisioning/bootstrapping
    session.pop("trigger_provisioning", None)
    return render_template("wait_for_bot.html")

@main_blueprint.route("/main", methods=["GET"])
def main_page():
    print(f"[main_web] main_page called from {request.path}")
    return render_template("main.html")
