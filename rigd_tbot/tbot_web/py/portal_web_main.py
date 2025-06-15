# tbot_web/py/portal_web_main.py
# Unified single Flask app for ALL bot phases, **blueprints are lazy-loaded** only when needed based on bot_state.txt

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from flask import Flask, render_template, send_from_directory, redirect, url_for, request, jsonify

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
STATIC_FOLDER = os.path.join(BASE_DIR, "static")
CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"

PHASES = {
    "initialize": "configuration",
    "configuration": "configuration",
    "provisioning": "provisioning",
    "bootstrapping": "bootstrapping",
    "registration": "registration",
    "main": "main",
    "idle": "main",
    "analyzing": "main",
    "monitoring": "main",
    "trading": "main",
    "updating": "main",
    "shutdown": "main",
    "graceful_closing_positions": "main",
    "emergency_closing_positions": "main",
    "shutdown_triggered": "main",
    "error": "main",
}

def get_bot_state():
    try:
        state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        return PHASES.get(state, "main")
    except Exception:
        return "main"

def create_unified_app():
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme-unsafe-dev-key")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    loaded_phase = None

    @app.before_request
    def lazy_load_blueprint():
        nonlocal loaded_phase
        state = get_bot_state()
        phase = PHASES.get(state, "main")
        if loaded_phase == phase:
            return  # Already loaded, nothing to do

        # Remove all existing blueprints except static
        keep = ["static"]
        for bp in list(app.blueprints):
            if bp not in keep:
                app.blueprints.pop(bp)

        # Dynamically import and register required blueprints for current phase
        if phase == "configuration":
            from .configuration_web import configuration_blueprint
            app.register_blueprint(configuration_blueprint, url_prefix="/configuration")
            from .main_web import main_blueprint
            app.register_blueprint(main_blueprint)
        elif phase == "provisioning":
            from .provisioning_web import provisioning_blueprint
            app.register_blueprint(provisioning_blueprint, url_prefix="/provisioning")
            from .main_web import main_blueprint
            app.register_blueprint(main_blueprint)
        elif phase == "bootstrapping":
            from .bootstrap_web import bootstrap_blueprint
            app.register_blueprint(bootstrap_blueprint, url_prefix="/bootstrapping")
            from .main_web import main_blueprint
            app.register_blueprint(main_blueprint)
        elif phase == "registration":
            from .register_web import register_web
            app.register_blueprint(register_web, url_prefix="/registration")
            from .main_web import main_blueprint
            app.register_blueprint(main_blueprint)
        else:  # main or any post-bootstrapping phase
            from .main_web import main_blueprint
            from .login_web import login_blueprint
            from .logout_web import logout_blueprint
            from .status_web import status_blueprint
            from .logs_web import logs_blueprint
            from .start_stop_web import start_stop_blueprint
            from .settings_web import settings_blueprint
            from .coa_web import coa_web
            from .ledger_web import ledger_web
            from .test_web import test_web
            app.register_blueprint(main_blueprint)
            app.register_blueprint(login_blueprint, url_prefix="/login")
            app.register_blueprint(logout_blueprint, url_prefix="/logout")
            app.register_blueprint(status_blueprint, url_prefix="/status")
            app.register_blueprint(logs_blueprint, url_prefix="/logs")
            app.register_blueprint(start_stop_blueprint, url_prefix="/control")
            app.register_blueprint(settings_blueprint, url_prefix="/settings")
            app.register_blueprint(coa_web, url_prefix="/coa")
            app.register_blueprint(ledger_web, url_prefix="/ledger")
            app.register_blueprint(test_web, url_prefix="/test")
        loaded_phase = phase

    @app.route("/")
    def root_router():
        state = get_bot_state()
        phase = PHASES.get(state, "main")
        if phase == "configuration":
            return redirect(url_for("configuration_web.show_configuration"))
        elif phase == "provisioning":
            return redirect(url_for("provisioning_web.provisioning_route"))
        elif phase == "bootstrapping":
            return redirect(url_for("bootstrap_web.bootstrap_route"))
        elif phase == "registration":
            return redirect(url_for("register_web.register_page"))
        else:
            return redirect(url_for("main.main_page"))

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(BASE_DIR, "favicon.ico")

    @app.route("/configuration/complete", methods=["POST"])
    def configuration_complete():
        return jsonify({"status": "configuration complete"}), 200

    @app.route("/healthz")
    def healthz():
        return jsonify({"status": "ok"}), 200

    return app

if __name__ == "__main__":
    app = create_unified_app()
    port = int(os.environ.get("PORT", 6900))
    app.run(host="0.0.0.0", port=port)
