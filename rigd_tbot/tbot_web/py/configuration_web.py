# tbot_web/py/configuration_web.py

from flask import Blueprint, request, render_template, flash, redirect, url_for, session
from ..support.default_config_loader import get_default_config
from pathlib import Path
from cryptography.fernet import Fernet
import json
from tbot_bot.support.bootstrap_utils import is_first_bootstrap
import subprocess

configuration_blueprint = Blueprint("configuration_web", __name__, url_prefix="/configuration")

RUNTIME_CONFIG_KEY_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "runtime_config.key"
RUNTIME_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "runtime_config.json.enc"
PROVISION_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "config" / "PROVISION_FLAG"
BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

def can_provision():
    if not BOT_STATE_PATH.exists():
        return True
    try:
        state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        return state == "initialize"
    except Exception:
        return False

def load_runtime_config():
    if RUNTIME_CONFIG_KEY_PATH.exists() and RUNTIME_CONFIG_PATH.exists():
        try:
            key = RUNTIME_CONFIG_KEY_PATH.read_bytes()
            fernet = Fernet(key)
            enc_bytes = RUNTIME_CONFIG_PATH.read_bytes()
            config_json = fernet.decrypt(enc_bytes).decode("utf-8")
            return json.loads(config_json)
        except Exception as e:
            print(f"[configuration_web] ERROR loading runtime config: {e}")
    return {}

def save_runtime_config(config: dict):
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

@configuration_blueprint.route("/", methods=["GET"])
def show_configuration():
    if not is_first_bootstrap():
        return redirect(url_for("main.main_page"))
    state = "initialize"
    if BOT_STATE_PATH.exists():
        try:
            state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        except Exception:
            state = "initialize"
    config = load_runtime_config()
    if not config and state == "initialize":
        config = get_default_config()
    return render_template("configuration.html", config=config)

@configuration_blueprint.route("/", methods=["POST"])
def save_configuration():
    if not can_provision() or not is_first_bootstrap():
        flash("Provisioning is locked after initial bootstrap. Use Settings to update configuration.", "error")
        return redirect(url_for("main.main_page"))

    form = request.form

    bot_identity_data = {
        "ENTITY_CODE":           form.get("entity_code", "").strip(),
        "JURISDICTION_CODE":     form.get("jurisdiction_code", "").strip(),
        "BROKER_CODE":           form.get("broker_name", "").strip(),
        "BOT_ID":                form.get("bot_id", "").strip(),
        "BOT_IDENTITY_STRING":   f"{form.get('entity_code','').strip()}_{form.get('jurisdiction_code','').strip()}_{form.get('broker_name','').strip()}_{form.get('bot_id','').strip()}"
    }
    broker_data = {
        "BROKER_CODE":           form.get("broker_name", "").strip(),
        "BROKER_URL":            form.get("broker_url", "").strip(),
        "BROKER_API_KEY":        form.get("broker_api_key", "").strip(),
        "BROKER_SECRET_KEY":     form.get("broker_secret_key", "").strip(),
        "BROKER_USERNAME":       form.get("broker_username", "").strip(),
        "BROKER_ACCOUNT_NUMBER": form.get("broker_account_number", "").strip(),
        "BROKER_PASSWORD":       form.get("broker_password", "").strip(),
    }
    screener_api_data = {
        "SCREENER_NAME":  form.get("screener_name", "").strip(),
        "FINNHUB_API_KEY":form.get("screener_api_key", "").strip()
    }
    smtp_data = {
        "ALERT_EMAIL":    form.get("alert_email", "").strip(),
        "SMTP_USER":      form.get("smtp_user", "").strip(),
        "SMTP_PASS":      form.get("smtp_pass", "").strip(),
        "SMTP_HOST":      form.get("smtp_host", "").strip(),
        "SMTP_PORT":      form.get("smtp_port", "").strip()
    }
    network_config_data = {
        "NETWORK_NAME": form.get("network_name", "").strip(),
        "HOSTNAME":     form.get("network_name", "").strip(),
        "HOST_IP":      form.get("ip", "").strip(),
        "PORT":         form.get("port", "").strip()
    }
    acct_api_data = {}

    language_code = form.get("language_code", "").strip() or "en"
    alert_channels = form.get("alert_channels", "").strip() or "email"

    config = {
        "bot_identity":    bot_identity_data,
        "broker":          broker_data,
        "screener_api":    screener_api_data,
        "smtp":            smtp_data,
        "network_config":  network_config_data,
        "acct_api":        acct_api_data,
        "language_code":   language_code,
        "alert_channels":  alert_channels,
    }

    save_runtime_config(config)

    try:
        BOT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BOT_STATE_PATH, "w", encoding="utf-8") as f:
            f.write("provisioning")
    except Exception as e:
        print(f"[configuration_web] ERROR writing bot_state.txt: {e}")

    try:
        PROVISION_FLAG_PATH.touch(exist_ok=True)
    except Exception as e:
        print(f"[configuration_web] ERROR writing PROVISION_FLAG: {e}")

    if is_first_bootstrap():
        try:
            subprocess.Popen(["python3", str(Path(__file__).resolve().parents[2] / "tbot_bot" / "config" / "provisioning_runner.py")])
            print("[configuration_web] provisioning_runner.py launched")
        except Exception as e:
            print(f"[configuration_web] ERROR launching provisioning_runner.py: {e}")

    session["trigger_provisioning"] = True
    session.modified = True
    flash("Configuration saved. Proceeding to provisioning...", "success")

    if is_first_bootstrap():
        return redirect(url_for("register_web.register_page"))
    else:
        return redirect(url_for("main.main_page"))
