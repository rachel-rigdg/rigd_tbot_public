# tbot_web/py/configuration_web.py

from flask import Blueprint, request, render_template, flash, redirect, url_for, session
from ..support.default_config_loader import get_default_config
from pathlib import Path
from cryptography.fernet import Fernet
import json
from tbot_bot.support.bootstrap_utils import is_first_bootstrap
import subprocess
import logging
import sys

configuration_blueprint = Blueprint("configuration_web", __name__, url_prefix="/configuration")

RUNTIME_CONFIG_KEY_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "runtime_config.key"
RUNTIME_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "runtime_config.json.enc"
PROVISION_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "config" / "PROVISION_FLAG"
BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
SECRETS_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "tools" / "secrets_template.json"

from tbot_bot.config import config_encryption

logger = logging.getLogger(__name__)

def load_runtime_config():
    if RUNTIME_CONFIG_KEY_PATH.exists() and RUNTIME_CONFIG_PATH.exists():
        try:
            key = RUNTIME_CONFIG_KEY_PATH.read_bytes()
            fernet = Fernet(key)
            enc_bytes = RUNTIME_CONFIG_PATH.read_bytes()
            config_json = fernet.decrypt(enc_bytes).decode("utf-8")
            return json.loads(config_json)
        except Exception as e:
            logger.error(f"[configuration_web] ERROR loading runtime config: {e}")
    return {}

def load_defaults():
    try:
        with open(SECRETS_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[configuration_web] ERROR loading default config from secrets_template.json: {e}")
    return {}

def save_runtime_config(config: dict):
    try:
        if not RUNTIME_CONFIG_KEY_PATH.exists():
            key = Fernet.generate_key()
            RUNTIME_CONFIG_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
            RUNTIME_CONFIG_KEY_PATH.write_bytes(key)
        else:
            key = RUNTIME_CONFIG_KEY_PATH.read_bytes()
        fernet = Fernet(key)
        enc_json = fernet.encrypt(json.dumps(config, indent=2).encode("utf-8"))
        RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_CONFIG_PATH.write_bytes(enc_json)
    except Exception as e:
        logger.error(f"[configuration_web] ERROR saving runtime config: {e}")
        raise

@configuration_blueprint.route("/", methods=["GET"])
def show_configuration():
    state = "initialize"
    if BOT_STATE_PATH.exists():
        try:
            state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        except Exception:
            state = "initialize"
    if state in ("provisioning", "bootstrapping"):
        return render_template("wait.html", bot_state=state)
    if state == "registration":
        return redirect(url_for("register_web.register_page"))
    config = load_runtime_config()
    if not config and state == "initialize":
        config = load_defaults()
    return render_template("configuration.html", config=config)

@configuration_blueprint.route("/", methods=["POST"])
def save_configuration():
    form = request.form

    bot_identity_data = {
        "ENTITY_CODE":           form.get("entity_code", "").strip(),
        "JURISDICTION_CODE":     form.get("jurisdiction_code", "").strip(),
        "BROKER_CODE":           form.get("broker_code", "").strip(),
        "BOT_ID":                form.get("bot_id", "").strip(),
        "BOT_IDENTITY_STRING":   f"{form.get('entity_code','').strip()}_{form.get('jurisdiction_code','').strip()}_{form.get('broker_code','').strip()}_{form.get('bot_id','').strip()}"
    }
    broker_data = {
        "BROKER_CODE":           form.get("broker_code", "").strip(),
        "BROKER_URL":            form.get("broker_url", "").strip(),
        "BROKER_API_KEY":        form.get("broker_api_key", "").strip(),
        "BROKER_SECRET_KEY":     form.get("broker_secret_key", "").strip(),
        "BROKER_USERNAME":       form.get("broker_username", "").strip(),
        "BROKER_ACCOUNT_NUMBER": form.get("broker_account_number", "").strip(),
        "BROKER_PASSWORD":       form.get("broker_password", "").strip(),
        "BROKER_TOKEN":          form.get("broker_token", "").strip(),
    }
        smtp_data = {
        "ALERT_EMAIL":    form.get("alert_email", "").strip(),
        "SMTP_USER":      form.get("smtp_user", "").strip(),
        "SMTP_PASS":      form.get("smtp_pass", "").strip(),
        "SMTP_HOST":      form.get("smtp_host", "").strip(),
        "SMTP_PORT":      form.get("smtp_port", "").strip()
    }
    network_config_data = {
        "HOSTNAME":   form.get("hostname", "").strip(),
        "HOST_IP":    form.get("ip", "").strip(),
        "PORT":       form.get("port", "").strip()
    }
    acct_api_data = {}

    language_code = form.get("language_code", "").strip() or "en"
    alert_channels = form.get("alert_channels", "").strip() or "email"
    debug_log_level = form.get("debug_log_level", "").strip() or "quiet"

    config = {
        "bot_identity":    bot_identity_data,
        "broker":          broker_data,
        "smtp":            smtp_data,
        "network_config":  network_config_data,
        "acct_api":        acct_api_data,
        "language_code":   language_code,
        "alert_channels":  alert_channels,
        "DEBUG_LOG_LEVEL": debug_log_level,
    }

    try:
        save_runtime_config(config)
        if not is_first_bootstrap():
            try:
                config_encryption.encrypt_and_write("bot_identity", bot_identity_data)
                config_encryption.encrypt_and_write("broker", broker_data)
                config_encryption.encrypt_and_write("smtp", smtp_data)
                config_encryption.encrypt_and_write("network_config", network_config_data)
                config_encryption.encrypt_and_write("acct_api", acct_api_data)
                config_encryption.encrypt_and_write("alert_channels", {"alert_channels": alert_channels})
            except Exception as e:
                logger.error(f"[configuration_web] ERROR updating encrypted secrets: {e}")
                flash("Failed to update secrets. See logs.", "error")
                return redirect(url_for("configuration_web.show_configuration"))
    except Exception:
        flash("Failed to save configuration. See logs.", "error")
        return redirect(url_for("configuration_web.show_configuration"))

    first_bootstrap = is_first_bootstrap()
    try:
        if first_bootstrap:
            BOT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(BOT_STATE_PATH, "w", encoding="utf-8") as f:
                f.write("provisioning")
            PROVISION_FLAG_PATH.touch(exist_ok=True)
            subprocess.Popen(["python3", str(Path(__file__).resolve().parents[2] / "tbot_bot" / "config" / "provisioning_runner.py")])
            logger.info("[configuration_web] provisioning_runner.py launched")
            session["trigger_provisioning"] = True
            session.modified = True
            flash("Configuration saved. Proceeding to provisioning...", "success")
            return render_template("wait.html", bot_state="provisioning")
        else:
            flash("Configuration saved.", "success")
            return redirect(url_for("configuration_web.show_configuration"))
    except Exception as e:
        logger.error(f"[configuration_web] ERROR during provisioning trigger: {e}")
        flash("Configuration saved, but provisioning trigger failed. Check logs.", "warning")
        return redirect(url_for("configuration_web.show_configuration"))
