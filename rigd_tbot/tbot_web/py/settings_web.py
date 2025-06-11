# tbot_web/py/settings_web.py
# Manages all trading strategy and runtime config variables (open/mid/close timings, analysis, monitoring, etc.) via web UI; excludes credentials

import sys
from flask import Blueprint, request, jsonify, render_template, abort, redirect, url_for
from tbot_web.py.login_web import login_required
from pathlib import Path
import tempfile
import os
import json

from tbot_web.py.bootstrap_utils import is_first_bootstrap

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from tbot_bot.config.env_bot import get_bot_config, validate_bot_config
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import validate_bot_identity, get_bot_identity_string_regex
from tbot_bot.config.security_bot import encrypt_env_bot_from_bytes

settings_blueprint = Blueprint("settings", __name__)

def get_valid_bot_identity_string():
    try:
        return load_bot_identity()
    except Exception:
        return None

@settings_blueprint.route("/settings")
@login_required
def settings_page():
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        config = get_bot_config()
        identity_string = config.get("BOT_IDENTITY_STRING", None)
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity or not identity_string or not get_bot_identity_string_regex().match(valid_identity):
            return render_template("settings.html", config=None, error="Bot identity not available, please complete configuration")
        validate_bot_identity(valid_identity)
    except Exception:
        return render_template("settings.html", config=None, error="Bot identity not available, please complete configuration")
    return render_template("settings.html", config=config, error=None)

@settings_blueprint.route("/settings.json", methods=["GET"])
@login_required
def get_settings():
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        config = get_bot_config()
        identity_string = config.get("BOT_IDENTITY_STRING", None)
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity or not identity_string or not get_bot_identity_string_regex().match(valid_identity):
            return jsonify({"error": "Bot identity not available, please complete configuration"}), 400
        validate_bot_identity(valid_identity)
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": "Bot identity not available, please complete configuration"}), 400

@settings_blueprint.route("/settings/update", methods=["POST"])
@login_required
def update_settings():
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    if not request.is_json:
        return jsonify({"status": "error", "detail": "Invalid JSON body"}), 400
    try:
        data = request.get_json()
        identity_string = data.get("BOT_IDENTITY_STRING", None)
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity or not identity_string or not get_bot_identity_string_regex().match(valid_identity):
            return jsonify({"status": "error", "detail": "Bot identity not available, please complete configuration"}), 400
        validate_bot_identity(valid_identity)
        validate_bot_config(data)
        raw_bytes = json.dumps(data, indent=2).encode("utf-8")
        encrypt_env_bot_from_bytes(raw_bytes, rotate_key=False)
        return jsonify({"status": "updated"})
    except Exception as e:
        return jsonify({"status": "error", "detail": "Bot identity not available, please complete configuration"}), 400

# Updated: Always loads bot identity via load_bot_identity(), checks validity, and handles missing/invalid identity gracefully with a UI error.
