# tbot_web/py/portal_web_registration.py
# Flask app for registration phase only

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from flask import Flask, send_from_directory, redirect, url_for, request, jsonify
from .register_web import register_web


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
STATIC_FOLDER = os.path.join(BASE_DIR, "static")

def create_registration_app():
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme-unsafe-dev-key")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    app.register_blueprint(register_web)

    @app.route("/")
    def serve_index():
        return redirect(url_for("register_web.register_page"))

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(BASE_DIR, "favicon.ico")

    @app.route("/registration/complete", methods=["POST"])
    def registration_complete():
        # Removed self-termination; phase_supervisor.py manages process lifecycle
        return jsonify({"status": "registration complete"}), 200

    return app

if __name__ == "__main__":
    app = create_registration_app()
    port = int(os.environ.get("PORT", 6904))
    app.run(host="0.0.0.0", port=port)
