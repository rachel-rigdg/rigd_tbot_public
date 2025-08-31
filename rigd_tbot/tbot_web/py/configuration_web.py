# tbot_web/py/configuration_web.py

from flask import Blueprint, request, render_template, flash, redirect, url_for, session
from ..support.default_config_loader import get_default_config
from pathlib import Path
from cryptography.fernet import Fernet
import json
from tbot_bot.support.bootstrap_utils import is_first_bootstrap
import subprocess
import logging

# ----------------------------
# [SCHEDULE LOCAL→UTC] minimal additions
# ----------------------------
import re
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo  # py>=3.9
except Exception:  # pragma: no cover
    ZoneInfo = None

# NEW: use centralized time helpers (DST-aware, UTC-first)
from tbot_bot.support.utils_time import (
    validate_hhmm as _utils_validate_hhmm,
    local_hhmm_to_utc_hhmm as _utils_local_to_utc_hhmm,
    nearest_market_day_reference as _utils_nearest_market_day_reference,
)

HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

def _validate_hhmm(label: str, v: str) -> str:
    """
    Delegate validation to utils_time.validate_hhmm for consistency.
    """
    v = (v or "").strip()
    if not _utils_validate_hhmm(v):
        raise ValueError(f"{label} must be HH:MM (24h). Got '{v}'.")
    return v

def _validate_timezone(v: str) -> str:
    v = (v or "").strip() or "UTC"
    if ZoneInfo is None and v != "UTC":
        raise ValueError("Timezone support unavailable; only 'UTC' allowed on this host.")
    try:
        _ = ZoneInfo(v) if ZoneInfo else None
        return v
    except Exception:
        raise ValueError(f"Invalid IANA timezone: '{v}'")

def _local_hhmm_to_utc_hhmm(hhmm: str, tzname: str) -> str:
    """
    Convert local HH:MM -> UTC HH:MM using utils_time (DST-aware).
    Anchors to nearest market-day reference date to avoid DST edge cases.
    """
    ref_date = _utils_nearest_market_day_reference(None, tzname)
    return _utils_local_to_utc_hhmm(hhmm, tzname, reference_date=ref_date)

def _update_env_lines(env_text: str, kv: dict) -> str:
    """Idempotently upsert keys in .env_bot while preserving comments/ordering."""
    lines = env_text.splitlines()
    pos = { }
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        k = line.split("=", 1)[0].strip()
        if k not in pos:
            pos[k] = i
    for k, v in kv.items():
        new_line = f"{k}={v}"
        if k in pos:
            lines[pos[k]] = new_line
        else:
            lines.append(new_line)
    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    return out

# ----------------------------

configuration_blueprint = Blueprint("configuration_web", __name__, url_prefix="/configuration")

RUNTIME_CONFIG_KEY_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "keys" / "runtime_config.key"
RUNTIME_CONFIG_PATH     = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "runtime_config.json.enc"
PROVISION_FLAG_PATH     = Path(__file__).resolve().parents[2] / "tbot_bot" / "config" / "PROVISION_FLAG"
BOT_STATE_PATH          = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
SECRETS_TEMPLATE_PATH   = Path(__file__).resolve().parents[2] / "tools"    / "secrets_template.json"

# [SCHEDULE LOCAL→UTC] .env_bot path (no path_resolver dependency to keep changes minimal)
ENV_BOT_PATH            = Path(__file__).resolve().parents[2] / ".env_bot"

from tbot_bot.config import config_encryption

logger = logging.getLogger(__name__)

def load_runtime_config():
    """Load and decrypt the runtime config if available."""
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
    """Load the default config template from secrets_template.json."""
    try:
        with open(SECRETS_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[configuration_web] ERROR loading default config from secrets_template.json: {e}")
    return {}

def save_runtime_config(config: dict):
    """Encrypt and write the runtime config to disk."""
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
    """Render the configuration page on first launch or during explicit reconfiguration."""
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

    # ----------------------------
    # [SCHEDULE LOCAL→UTC] ensure both LOCAL inputs and UTC previews exist
    # ----------------------------
    config.setdefault("TIMEZONE", "UTC")
    config.setdefault("START_TIME_OPEN_LOCAL",  "09:30")
    config.setdefault("START_TIME_MID_LOCAL",   "12:00")
    config.setdefault("START_TIME_CLOSE_LOCAL", "15:45")
    config.setdefault("START_TIME_OPEN",  config.get("START_TIME_OPEN",  ""))   # UTC preview
    config.setdefault("START_TIME_MID",   config.get("START_TIME_MID",   ""))   # UTC preview
    config.setdefault("START_TIME_CLOSE", config.get("START_TIME_CLOSE", ""))   # UTC preview
    config.setdefault("MARKET_CLOSE_UTC", config.get("MARKET_CLOSE_UTC", ""))   # UTC preview
    # ----------------------------

    return render_template("configuration.html", config=config)

@configuration_blueprint.route("/", methods=["POST"])
def save_configuration():
    """Save posted configuration form and trigger provisioning if required."""
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

    # --- TIMEZONE support (existing behavior retained) ---
    timezone_val = form.get("timezone", "").strip() or "UTC"

    # ----------------------------
    # [SCHEDULE LOCAL→UTC] validate inputs and derive UTC once
    # ----------------------------
    try:
        tz_valid     = _validate_timezone(timezone_val)
        open_local   = _validate_hhmm("Open (Local)",  form.get("start_time_open_local",  "09:30"))
        mid_local    = _validate_hhmm("Mid (Local)",   form.get("start_time_mid_local",   "12:00"))
        close_local  = _validate_hhmm("Close (Local)", form.get("start_time_close_local", "15:45"))

        open_utc     = _local_hhmm_to_utc_hhmm(open_local,  tz_valid)
        mid_utc      = _local_hhmm_to_utc_hhmm(mid_local,   tz_valid)
        close_utc    = _local_hhmm_to_utc_hhmm(close_local, tz_valid)
        # Market close default 16:00 local; if later you add a local field, convert that instead.
        market_close_utc = _local_hhmm_to_utc_hhmm("16:00", tz_valid)
    except ValueError as ve:
        flash(str(ve), "error")
        return redirect(url_for("configuration_web.show_configuration"))
    except Exception as e:
        logger.error(f"[configuration_web] Local→UTC conversion failed: {e}")
        flash("Failed to convert local schedule times to UTC. Check timezone and HH:MM inputs.", "error")
        return redirect(url_for("configuration_web.show_configuration"))
    # ----------------------------

    config = {
        "bot_identity":    bot_identity_data,
        "broker":          broker_data,
        "smtp":            smtp_data,
        "network_config":  network_config_data,
        "acct_api":        acct_api_data,
        "language_code":   language_code,
        "alert_channels":  alert_channels,
        "DEBUG_LOG_LEVEL": debug_log_level,
        # ----------------------------
        # [SCHEDULE LOCAL→UTC] persist both LOCAL inputs and derived UTC to runtime_config
        # ----------------------------
        "TIMEZONE":                 tz_valid,
        "SCHEDULE_INPUT_TZ":        "UTC",  # runtime strictly reads UTC keys
        "START_TIME_OPEN_LOCAL":    open_local,
        "START_TIME_MID_LOCAL":     mid_local,
        "START_TIME_CLOSE_LOCAL":   close_local,
        "START_TIME_OPEN":          open_utc,
        "START_TIME_MID":           mid_utc,
        "START_TIME_CLOSE":         close_utc,
        "MARKET_CLOSE_UTC":         market_close_utc,
        # ----------------------------
    }

    try:
        save_runtime_config(config)
        # Only update encrypted secrets if this is not the first bootstrap
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

    # ----------------------------
    # [SCHEDULE LOCAL→UTC] upsert schedule block into plain .env_bot (atomic-ish)
    # ----------------------------
    try:
        ENV_BOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = ENV_BOT_PATH.read_text(encoding="utf-8") if ENV_BOT_PATH.exists() else ""
        upserts = {
            "TIMEZONE":               tz_valid,
            "SCHEDULE_INPUT_TZ":      "UTC",
            "START_TIME_OPEN_LOCAL":  open_local,
            "START_TIME_MID_LOCAL":   mid_local,
            "START_TIME_CLOSE_LOCAL": close_local,
            "START_TIME_OPEN":        open_utc,
            "START_TIME_MID":         mid_utc,
            "START_TIME_CLOSE":       close_utc,
            "MARKET_CLOSE_UTC":       market_close_utc,
        }
        merged = _update_env_lines(existing, upserts)
        tmp = ENV_BOT_PATH.with_suffix(".tmp")
        tmp.write_text(merged, encoding="utf-8")
        tmp.replace(ENV_BOT_PATH)
    except Exception as e:
        logger.error(f"[configuration_web] ERROR writing .env_bot: {e}")
        flash("Configuration saved, but failed to update .env_bot schedule keys. See logs.", "warning")
    # ----------------------------

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
            flash(
                f"Configuration saved. Times (Local→UTC): "
                f"Open {open_local}→{open_utc}, Mid {mid_local}→{mid_utc}, Close {close_local}→{close_utc}, MarketClose →{market_close_utc} UTC. "
                f"Proceeding to provisioning...",
                "success"
            )
            return render_template("wait.html", bot_state="provisioning")
        else:
            flash(
                f"Configuration saved. Times (Local→UTC): "
                f"Open {open_local}→{open_utc}, Mid {mid_local}→{mid_utc}, Close {close_local}→{close_utc}, MarketClose →{market_close_utc} UTC.",
                "success"
            )
            return redirect(url_for("configuration_web.show_configuration"))
    except Exception as e:
        logger.error(f"[configuration_web] ERROR during provisioning trigger: {e}")
        flash(
            f"Configuration saved (Local→UTC persisted), but provisioning trigger failed. Check logs.",
            "warning"
        )
        return redirect(url_for("configuration_web.show_configuration"))
