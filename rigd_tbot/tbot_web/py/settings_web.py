# tbot_web/py/settings_web.py
# Manages all trading strategy and runtime config variables (open/mid/close timings, analysis, monitoring, etc.) via web UI; excludes credentials

import sys
from flask import Blueprint, request, jsonify, render_template, abort, redirect, url_for
from tbot_web.py.login_web import login_required  # Corrected import per directory spec
from pathlib import Path
import tempfile
import shutil

from tbot_web.py.bootstrap_utils import is_first_bootstrap  # Use utility module for bootstrap

# Ensure root path is in sys.path to resolve tbot_bot modules
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from tbot_bot.config.settings_bot import read_env_bot, write_env_bot
from tbot_bot.support.path_resolver import validate_bot_identity

# Robust and secure encryption routine
def rotate_and_encrypt_env_bot():
    """
    Calls the .env_bot encryptor with key rotation.
    """
    import subprocess
    security_bot_path = PROJECT_ROOT / "tbot_bot" / "config" / "security_bot.py"
    subprocess.check_call([sys.executable, str(security_bot_path), "rotate"])

settings_blueprint = Blueprint("settings", __name__)

@settings_blueprint.route("/settings")
@login_required
def settings_page():
    """
    Renders the config form UI with decrypted .env_bot values.
    """
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        config = read_env_bot()
        validate_bot_identity(config.get("BOT_IDENTITY_STRING", "INVALID_IDENTITY"))
    except Exception as e:
        abort(500, description=f"Failed to load config: {e}")
    return render_template("settings.html", config=config)

@settings_blueprint.route("/settings.json", methods=["GET"])
@login_required
def get_settings():
    """
    API endpoint: returns current .env_bot values as JSON.
    """
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        config = read_env_bot()
        validate_bot_identity(config.get("BOT_IDENTITY_STRING", "INVALID_IDENTITY"))
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@settings_blueprint.route("/settings/update", methods=["POST"])
@login_required
def update_settings():
    """
    API endpoint: receives config JSON, writes to temp file, then calls robust encryptor.
    """
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    if not request.is_json:
        return jsonify({"status": "error", "detail": "Invalid JSON body"}), 400

    try:
        data = request.get_json()
        validate_bot_identity(data.get("BOT_IDENTITY_STRING", "INVALID_IDENTITY"))

        # Write to temp .env_bot, then atomically move into place
        env_bot_path = Path(PROJECT_ROOT) / "tbot_bot" / "support" / ".env_bot"
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
            for key, value in data.items():
                if "\n" in str(value) or "\r" in str(value):
                    # Sanitize newlines to prevent injection or formatting errors
                    value = value.replace("\n", " ").replace("\r", " ")
                tf.write(f"{key}={value}\n")
            temp_path = Path(tf.name)
        shutil.move(str(temp_path), env_bot_path)

        # Now call security_bot to rotate key and re-encrypt
        rotate_and_encrypt_env_bot()

        return jsonify({"status": "updated"})
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500
