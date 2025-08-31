# tbot_web/py/portal_web_main.py
# Unified single Flask app for ALL bot phases; all blueprints are statically registered up-front.
# First bootstrap is enforced by a before_request redirect, never by dynamic blueprint loading.

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

try:
    from tbot_bot.support.bootstrap_utils import is_first_bootstrap
except ImportError:
    is_first_bootstrap = lambda: False

def get_bot_state():
    try:
        state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        print(f"[portal_web_main] get_bot_state: state={state}")
        return state
    except Exception as e:
        print(f"[portal_web_main] get_bot_state EXCEPTION: {e}")
        return "unknown"

def create_unified_app():
    print("[portal_web_main] Creating Flask app...")
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme-unsafe-dev-key")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    # Use absolute imports for blueprints
    from tbot_web.py.main_web import main_blueprint
    from tbot_web.py.configuration_web import configuration_blueprint
    from tbot_web.py.login_web import login_blueprint
    from tbot_web.py.logout_web import logout_blueprint
    from tbot_web.py.status_web import status_blueprint
    from tbot_web.py.logs_web import logs_blueprint
    from tbot_web.py.start_stop_web import start_stop_blueprint
    from tbot_web.py.settings_web import settings_blueprint
    from tbot_web.py.coa_web import coa_web
    from tbot_web.py.ledger_web import ledger_web
    from tbot_web.py.test_web import test_web
    from tbot_web.py.register_web import register_web
    from tbot_web.py.universe_web import universe_bp
    from tbot_web.py.password_reset_web import password_reset_blueprint
    from tbot_web.py.users_web import users_blueprint
    from tbot_web.py.account_web import account_blueprint
    from tbot_web.py.screener_credentials_web import screener_credentials_bp
    from tbot_web.py.holdings_web import holdings_web
    from tbot_web.py.coa_mapping_web import coa_mapping_web  # NEW: COA mapping UI routes

    # Always register required blueprints
    app.register_blueprint(register_web, url_prefix="/registration")
    app.register_blueprint(main_blueprint)
    app.register_blueprint(configuration_blueprint)
    app.register_blueprint(login_blueprint, url_prefix="/login")
    app.register_blueprint(logout_blueprint, url_prefix="/logout")
    app.register_blueprint(status_blueprint, url_prefix="/status")
    app.register_blueprint(logs_blueprint, url_prefix="/logs")
    app.register_blueprint(start_stop_blueprint, url_prefix="/control")
    app.register_blueprint(settings_blueprint, url_prefix="/settings")
    app.register_blueprint(coa_web, url_prefix="/coa")
    app.register_blueprint(ledger_web, url_prefix="/ledger")
    app.register_blueprint(test_web, url_prefix="/test")
    app.register_blueprint(universe_bp, url_prefix="/universe")
    app.register_blueprint(password_reset_blueprint, url_prefix="/password_reset")
    app.register_blueprint(users_blueprint, url_prefix="/users")
    app.register_blueprint(account_blueprint, url_prefix="/account")
    app.register_blueprint(screener_credentials_bp, url_prefix="/screener_credentials")
    app.register_blueprint(holdings_web, url_prefix="/holdings")
    app.register_blueprint(coa_mapping_web)  # NEW: expose /coa_mapping routes (no prefix)

    @app.before_request
    def enforce_bootstrap():
        if is_first_bootstrap():
            # During bootstrap, only allow config, registration, provisioning, static
            if not (
                (request.endpoint or "").startswith("configuration_web")
                or (request.endpoint or "").startswith("register_web")
                or (request.endpoint or "").startswith("main.provisioning_route")
                or request.path.startswith("/static")
            ):
                return redirect(url_for("configuration_web.show_configuration"))

    # Serve /static/output/screeners/* from tbot_bot/output/screeners, with bootstrap gating
    @app.route('/static/output/screeners/<path:filename>')
    def output_screeners_static(filename):
        if is_first_bootstrap():
            return "Access denied during bootstrap", 403
        screeners_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'tbot_bot', 'output', 'screeners'))
        return send_from_directory(screeners_dir, filename)

    print("==== ROUTES ====")
    for rule in app.url_map.iter_rules():
        print(rule, rule.endpoint)
    print("===============")

    @app.route("/")
    def root_router():
        return redirect(url_for("main.root_router"))

    @app.route("/favicon.ico")
    def favicon():
        print("[portal_web_main] /favicon.ico requested")
        return send_from_directory(BASE_DIR, "favicon.ico")

    @app.route("/healthz")
    def healthz():
        print("[portal_web_main] /healthz requested")
        return jsonify({"status": "ok"}), 200

    @app.route("/api/bot_state")
    def api_bot_state():
        state = get_bot_state()
        return jsonify({"bot_state": state})

    return app

if __name__ == "__main__":
    print("[portal_web_main] __main__ entry, launching unified Flask app...")
    app = create_unified_app()
    port = int(os.environ.get("PORT", 6900))
    print(f"[portal_web_main] Listening on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
