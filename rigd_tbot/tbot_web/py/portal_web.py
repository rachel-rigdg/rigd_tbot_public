# tbot_web/py/portal_web.py
# Unified Flask app factory for app + static + template setup (web UI only; no provisioning logic or privileged imports)

import os
from flask import Flask, render_template, send_from_directory, redirect, url_for, request, jsonify
from .main_web import main_blueprint
from .configuration_web import configuration_blueprint
from .login_web import login_blueprint
from .logout_web import logout_blueprint
from .status_web import status_blueprint
from .logs_web import logs_blueprint
from .start_stop_web import start_stop_blueprint
from .settings_web import settings_blueprint
from .coa_web import coa_web
from .bootstrap_utils import is_first_bootstrap

from tbot_web.support import auth_web, security_users, session_manager, utils_web, csrf_protection

from pathlib import Path

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
STATIC_FOLDER = os.path.join(BASE_DIR, "static")

def create_app():
    """
    Creates the Flask app with all route blueprints registered.
    On first bootstrap, routes all requests to configuration page.
    No privileged/provisioning logic is present here; web UI only.
    """
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme-unsafe-dev-key")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    # Register all web UI blueprints; never register any provisioning/runner/ledger blueprints at app start
    app.register_blueprint(main_blueprint)
    app.register_blueprint(configuration_blueprint)
    app.register_blueprint(login_blueprint)
    app.register_blueprint(status_blueprint)
    app.register_blueprint(logs_blueprint)
    app.register_blueprint(start_stop_blueprint)
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(coa_web)
    app.register_blueprint(logout_blueprint)

    # Route for wait_for_bot.html
    @app.route("/wait_for_bot")
    def wait_for_bot():
        return render_template("wait_for_bot.html")

    # Control status endpoint for polling control_start.txt
    @app.route("/control_status/start")
    def control_status_start():
        control_path = Path(BASE_DIR) / ".." / "tbot_bot" / "control" / "control_start.txt"
        if control_path.exists():
            return jsonify({"status": "started"})
        else:
            return jsonify({"status": "pending"})

    # First-boot mode: redirect all requests to /configuration if not configured
    if is_first_bootstrap():
        @app.before_request
        def force_configuration():
            if not (
                (request.endpoint or "").startswith("configuration_web")
                or (request.endpoint or "").startswith("main.provisioning_route")
                or request.path.startswith("/static")
            ):
                return redirect(url_for("configuration_web.show_configuration"))
        print("==== ROUTES (BOOTSTRAP MODE) ====")
        for rule in app.url_map.iter_rules():
            print(rule, rule.endpoint)
        print("===============")
        return app

    print("==== ROUTES (NORMAL MODE) ====")
    for rule in app.url_map.iter_rules():
        print(rule, rule.endpoint)
    print("===============")

    # Fallback root if no main blueprint catches "/"
    @app.route("/")
    def serve_index():
        return render_template("index.html")

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(BASE_DIR, "favicon.ico")

    return app
