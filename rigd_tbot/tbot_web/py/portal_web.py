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
from pathlib import Path

from tbot_web.support import auth_web, security_users, session_manager, utils_web, csrf_protection

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
STATIC_FOLDER = os.path.join(BASE_DIR, "static")
BOT_STATE_PATH = Path(BASE_DIR) / ".." / "tbot_bot" / "control" / "bot_state.txt"

def get_bot_state():
    try:
        if BOT_STATE_PATH.exists():
            return BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        return "initialize"
    except Exception:
        return "initialize"

def create_app():
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme-unsafe-dev-key")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    app.register_blueprint(main_blueprint)
    app.register_blueprint(configuration_blueprint)
    app.register_blueprint(login_blueprint)
    app.register_blueprint(status_blueprint)
    app.register_blueprint(logs_blueprint)
    app.register_blueprint(start_stop_blueprint)
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(coa_web)
    app.register_blueprint(logout_blueprint)

    @app.before_request
    def force_configuration():
        # Always check bot_state.txt before every request
        state = get_bot_state()
        if state == "initialize":
            if not (
                (request.endpoint or "").startswith("configuration_web")
                or (request.endpoint or "").startswith("main.provisioning_route")
                or request.path.startswith("/static")
            ):
                return redirect(url_for("configuration_web.show_configuration"))

    @app.route("/wait")
    def wait():
        return render_template("wait.html")

    @app.route("/main")
    def main():
        return render_template("main.html")

    @app.route("/control_status/start")
    def control_status_start():
        try:
            state = get_bot_state()
            if state in ("initialize", "provisioning", "bootstrapping"):
                return jsonify({"status": state, "bot_state": state})
            elif state in ("error", "shutdown_triggered", "shutdown"):
                return jsonify({"status": "error", "bot_state": state})
            else:
                return jsonify({"status": "started", "bot_state": state})
        except Exception:
            return jsonify({"status": "error", "bot_state": "error"})

    @app.route("/")
    def serve_index():
        return render_template("index.html")

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(BASE_DIR, "favicon.ico")

    return app
