# tbot_web/py/portal_web_provision.py
# Flask entry point for provisioning phase

import os
from flask import Flask, redirect, url_for, send_from_directory
from .main_web import main_blueprint
from .provisioning_web import provisioning_blueprint
from pathlib import Path

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
STATIC_FOLDER = os.path.join(BASE_DIR, "static")

def create_provision_app():
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme-unsafe-dev-key")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    app.register_blueprint(main_blueprint)
    app.register_blueprint(provisioning_blueprint)

    @app.route("/")
    def serve_provision():
        return redirect(url_for("main.provisioning_route"))

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(BASE_DIR, "favicon.ico")

    return app

if __name__ == "__main__":
    app = create_provision_app()
    port = int(os.environ.get("PORT", 6902))
    app.run(host="0.0.0.0", port=port)
