# tbot_web/py/logs_web.py
# Displays latest bot log output to the web UI

from flask import Blueprint, render_template, redirect, url_for
from tbot_web.py.login_web import login_required
from pathlib import Path
import glob
from tbot_bot.support.path_resolver import get_output_path, validate_bot_identity
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.utils_log import log_event
from tbot_web.py.bootstrap_utils import is_first_bootstrap

logs_blueprint = Blueprint("logs", __name__)

LOG_FILES_TO_INCLUDE = [
    "main_bot.log",
    "strategy_open.log",
    "strategy_mid.log",
    "strategy_close.log",
    "heartbeat.log",
    "watchdog_bot.log",
    "router.log",
    "screener.log",
    "kill_switch.log",
    "provisioning.log",
    "error_tracebacks.log",
    "auth_web.log",
    "security_users.log",
    "init_system_logs.log",
    "init_system_users.log",
    "init_user_activity_monitoring.log",
    "init_password_reset_tokens.log"
]

@logs_blueprint.route("/logs")
@login_required
def logs_page():
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))

    log_content = ""
    try:
        bot_identity_string = load_bot_identity()
        validate_bot_identity(bot_identity_string)
        logs_dir = get_output_path(bot_identity_string, "logs")

        log_texts = []
        for log_file_name in LOG_FILES_TO_INCLUDE:
            file_path = logs_dir / log_file_name
            if file_path.is_file():
                try:
                    log_texts.append(f"==== {log_file_name} ====\n")
                    log_texts.append(file_path.read_text(encoding="utf-8"))
                    log_texts.append("\n\n")
                except Exception as e:
                    log_event("logs_web", f"Failed to read {file_path}: {e}", level="warning")
            else:
                log_event("logs_web", f"Log file missing: {file_path}", level="warning")

        log_content = "".join(log_texts) if log_texts else "No log files found."

    except Exception as e:
        log_content = f"[logs_web] Error loading logs: {e}"
        log_event("logs_web", f"Exception while loading logs: {e}", level="error")

    return render_template("logs.html", log_text=log_content)
