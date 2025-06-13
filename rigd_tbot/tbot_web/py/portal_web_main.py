# tbot_web/py/portal_web_main.py
# Flask app for main (post-registration) operational UI

import os
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
from pathlib import Path

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
STATIC_FOLDER = os.path.join(BASE_DIR, "static")

def create_main_app():
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme-unsafe-dev-key")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    app.register_blueprint(main_blueprint)
    app.register_blueprint(login_blueprint)
    app.register_blueprint(logout_blueprint)
    app.register_blueprint(status_blueprint)
    app.register_blueprint(logs_blueprint)
    app.register_blueprint(start_stop_blueprint)
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(coa_web)
    app.register_blueprint(ledger_web)
    app.register_blueprint(test_web)

    @app.route("/")
    def serve_index():
        return redirect(url_for("main.main_page"))

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(BASE_DIR, "favicon.ico")

    return app
