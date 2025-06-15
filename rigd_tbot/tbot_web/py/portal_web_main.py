# tbot_web/py/portal_web_main.py
# Unified single Flask app for ALL bot phases, **blueprints are lazy-loaded** only when needed based on bot_state.txt

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from flask import Flask, render_template, send_from_directory, redirect, url_for, request, jsonify

print("[portal_web_main] Starting portal_web_main.py...")

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
        print(f"[portal_web_main] get_bot_state: state={state}")
        return PHASES.get(state, "main")
    except Exception as e:
        print(f"[portal_web_main] get_bot_state EXCEPTION: {e}")
        return "main"

def create_unified_app():
    print("[portal_web_main] Creating Flask app...")
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
        print(f"[portal_web_main] before_request: loaded_phase={loaded_phase}, requested_phase={phase}")

        if loaded_phase == phase:
            print(f"[portal_web_main] Phase '{phase}' already loaded. No action.")
            return  # Already loaded, nothing to do

        # Remove all existing blueprints except static
        keep = ["static"]
        for bp in list(app.blueprints):
            if bp not in keep:
                print(f"[portal_web_main] Removing blueprint: {bp}")
                app.blueprints.pop(bp)

        # Dynamically import and register required blueprints for current phase
        print(f"[portal_web_main] Loading blueprints for phase: {phase}")
        if phase == "configuration":
            from .configuration_web import configuration_blueprint
            app.register_blueprint(configuration_blueprint, url_prefix="/configuration")
            print("[portal_web_main] Registered: configuration_blueprint")
            from .main_web import main_blueprint
            app.register_blueprint(main_blueprint)
            print("[portal_web_main] Registered: main_blueprint")
        elif phase == "provisioning":
            from .provisioning_web import provisioning_blueprint
            app.register_blueprint(provisioning_blueprint, url_prefix="/provisioning")
            print("[portal_web_main] Registered: provisioning_blueprint")
            from .main_web import main_blueprint
            app.register_blueprint(main_blueprint)
            print("[portal_web_main] Registered: main_blueprint")
        elif phase == "bootstrapping":
            from .bootstrap_web import bootstrap_blueprint
            app.register_blueprint(bootstrap_blueprint, url_prefix="/bootstrapping")
            print("[portal_web_main] Registered: bootstrap_blueprint")
            from .main_web import main_blueprint
            app.register_blueprint(main_blueprint)
            print("[portal_web_main] Registered: main_blueprint")
        elif phase == "registration":
            from .register_web import register_web
            app.register_blueprint(register_web, url_prefix="/registration")
            print("[portal_web_main] Registered: register_web")
            from .main_web import main_blueprint
            app.register_blueprint(main_blueprint)
            print("[portal_web_main] Registered: main_blueprint")
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
            print("[portal_web_main] Registered: main_blueprint")
            app.register_blueprint(login_blueprint, url_prefix="/login")
            print("[portal_web_main] Registered: login_blueprint")
            app.register_blueprint(logout_blueprint, url_prefix="/logout")
            print("[portal_web_main] Registered: logout_blueprint")
            app.register_blueprint(status_blueprint, url_prefix="/status")
            print("[portal_web_main] Registered: status_blueprint")
            app.register_blueprint(logs_blueprint, url_prefix="/logs")
            print("[portal_web_main] Registered: logs_blueprint")
            app.register_blueprint(start_stop_blueprint, url_prefix="/control")
            print("[portal_web_main] Registered: start_stop_blueprint")
            app.register_blueprint(settings_blueprint, url_prefix="/settings")
            print("[portal_web_main] Registered: settings_blueprint")
            app.register_blueprint(coa_web, url_prefix="/coa")
            print("[portal_web_main] Registered: coa_web")
            app.register_blueprint(ledger_web, url_prefix="/ledger")
            print("[portal_web_main] Registered: ledger_web")
            app.register_blueprint(test_web, url_prefix="/test")
            print("[portal_web_main] Registered: test_web")
        loaded_phase = phase
        print(f"[portal_web_main] loaded_phase set to: {loaded_phase}")

    @app.route("/")
    def root_router():
        state = get_bot_state()
        phase = PHASES.get(state, "main")
        print(f"[portal_web_main] root_router: phase={phase}")
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
        print("[portal_web_main] /favicon.ico requested")
        return send_from_directory(BASE_DIR, "favicon.ico")

    @app.route("/configuration/complete", methods=["POST"])
    def configuration_complete():
        print("[portal_web_main] /configuration/complete POST called")
        return jsonify({"status": "configuration complete"}), 200

    @app.route("/healthz")
    def healthz():
        print("[portal_web_main] /healthz requested")
        return jsonify({"status": "ok"}), 200

    print("[portal_web_main] Flask app created successfully.")
    return app

if __name__ == "__main__":
    print("[portal_web_main] __main__ entry, launching unified Flask app...")
    app = create_unified_app()
    port = int(os.environ.get("PORT", 6900))
    print(f"[portal_web_main] Listening on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
