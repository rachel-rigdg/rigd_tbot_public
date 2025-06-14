# tbot_web/py/portal_web_configuration.py
# Flask app for configuration phase (configuration.html UI)

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from flask import Flask, render_template, send_from_directory, redirect, url_for, request, jsonify
from .main_web import main_blueprint
from .configuration_web import configuration_blueprint
from pathlib import Path

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
STATIC_FOLDER = os.path.join(BASE_DIR, "static")

def create_configuration_app():
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "changeme-unsafe-dev-key")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    app.register_blueprint(main_blueprint)
    app.register_blueprint(configuration_blueprint, url_prefix="/configuration")

    @app.route("/")
    def serve_configuration():
        return redirect(url_for("configuration_web.show_configuration"))

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(BASE_DIR, "favicon.ico")

    @app.route("/configuration/complete", methods=["POST"])
    def configuration_complete():
        # Removed self-termination; phase_supervisor.py manages process lifecycle
        return jsonify({"status": "configuration complete"}), 200

    return app

if __name__ == "__main__":
    app = create_configuration_app()
    # Use dedicated port for configuration phase to avoid port conflicts.
    port = int(os.environ.get("PORT", 6901))
    app.run(host="0.0.0.0", port=port)
