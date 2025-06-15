# tbot_web/py/portal_web_main.py
# Unified operational Flask app for all non-configuration phases
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from flask import Flask, render_template, send_from_directory, redirect, url_for, request, jsonify

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

# Provisioning and bootstrapping blueprints/endpoints
from .provisioning_web import provisioning_blueprint
from .bootstrap_web import bootstrap_blueprint
from .register_web import register_web

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
STATIC_FOLDER = os.path.join(BASE_DIR, "static")
CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"

PHASES = {
    "provisioning": provisioning_blueprint,
    "bootstrapping": bootstrap_blueprint,
    "registration": register_web,
    "main": main_blueprint,
    "idle": main_blueprint,
    "analyzing": main_blueprint,
    "monitoring": main_blueprint,
    "trading": main_blueprint,
    "updating": main_blueprint,
    "shutdown": main_blueprint,
    "graceful_closing_positions": main_blueprint,
    "emergency_closing_positions": main_blueprint,
    "shutdown_triggered": main_blueprint,
    "error": main_blueprint,
}

def get_bot_state():
    try:
        state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        return state
    except Exception:
        return "main"

def create_main_app():
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme-unsafe-dev-key")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    # Always available core blueprints
    app.register_blueprint(login_blueprint, url_prefix="/login")
    app.register_blueprint(logout_blueprint, url_prefix="/logout")
    app.register_blueprint(status_blueprint, url_prefix="/status")
    app.register_blueprint(logs_blueprint, url_prefix="/logs")
    app.register_blueprint(start_stop_blueprint, url_prefix="/control")
    app.register_blueprint(settings_blueprint, url_prefix="/settings")
    app.register_blueprint(coa_web, url_prefix="/coa")
    app.register_blueprint(ledger_web, url_prefix="/ledger")
    app.register_blueprint(test_web, url_prefix="/test")

    # Lazy-load phase-specific blueprints on first request per phase
    registered_phases = set()
    @app.before_request
    def load_phase_blueprint():
        state = get_bot_state()
        bp = PHASES.get(state)
        if bp and bp.name not in app.blueprints and bp.name not in registered_phases:
            app.register_blueprint(bp)
            registered_phases.add(bp.name)

    @app.route("/")
    def serve_index():
        state = get_bot_state()
        if state in ("provisioning",):
            return redirect(url_for("provisioning_web.provisioning_route"))
        elif state in ("bootstrapping",):
            return redirect(url_for("bootstrap_web.bootstrap_route"))
        elif state in ("registration",):
            return redirect(url_for("register_web.register_page"))
        else:
            return redirect(url_for("main.main_page"))

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(BASE_DIR, "favicon.ico")

    return app

if __name__ == "__main__":
    app = create_main_app()
    port = int(os.environ.get("PORT", 6900))
    app.run(host="0.0.0.0", port=port)
