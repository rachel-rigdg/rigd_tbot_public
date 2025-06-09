# tbot_web/py/configuration_web.py

from flask import Blueprint, request, render_template, flash, redirect, url_for, session
from ..support.configuration_loader import load_encrypted_config
from ..support.default_config_loader import get_default_config
from pathlib import Path
import json

configuration_blueprint = Blueprint("configuration_web", __name__)

TMP_CONFIG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "support" / "tmp" / "bootstrap_config.json"
PROVISION_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "config" / "PROVISION_FLAG"
BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

def can_provision():
    if not BOT_STATE_PATH.exists():
        return True
    try:
        state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        return state in ("initialize", "provisioning")
    except Exception:
        return False

@configuration_blueprint.route("/configuration", methods=["GET"])
def show_configuration():
    print("[configuration_web] Rendering configuration page")
    config = {}
    categories = [
        "bot_identity", "broker", "screener_api",
        "smtp", "network_config", "acct_api"
    ]
    for cat in categories:
        config.update(load_encrypted_config(cat))
    if not config:
        config = get_default_config()
    return render_template("configuration.html", config=config)

@configuration_blueprint.route("/configuration", methods=["POST"])
def save_configuration():
    print("[configuration_web] Received POST to /configuration")
    if not can_provision():
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

    config = {
        "bot_identity":    bot_identity_data,
        "broker":          broker_data,
        "screener_api":    screener_api_data,
        "smtp":            smtp_data,
        "network_config":  network_config_data,
        "acct_api":        acct_api_data
    }

    # Write full config with BOT_IDENTITY_STRING to tmp for provisioning_helper.py
    TMP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TMP_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

    try:
        BOT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BOT_STATE_PATH, "w", encoding="utf-8") as f:
            f.write("provisioning")
    except Exception as e:
        print(f"[configuration_web] ERROR writing bot_state.txt: {e}")

    try:
        PROVISION_FLAG_PATH.touch(exist_ok=True)
        print(f"[configuration_web] PROVISION_FLAG written: {PROVISION_FLAG_PATH}")
    except Exception as e:
        print(f"[configuration_web] ERROR writing PROVISION_FLAG: {e}")

    print("[configuration_web] Configuration saved. Triggering provisioning on redirect.")
    session["trigger_provisioning"] = True
    session.modified = True
    flash("Configuration saved. Proceeding to provisioning...", "success")
    return redirect(url_for("main.provisioning_route"))
