# tbot_web/py/logs_web.py
# Displays latest bot log output to the web UI

from flask import Blueprint, render_template, redirect, url_for
from tbot_web.py.login_web import login_required  # Corrected import per directory spec
from pathlib import Path
from tbot_bot.support.path_resolver import get_output_path, validate_bot_identity
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.utils_log import log_event
from tbot_web.py.bootstrap_utils import is_first_bootstrap  # Use utility module

logs_blueprint = Blueprint("logs", __name__)

@logs_blueprint.route("/logs")
@login_required
def logs_page():
    """
    Protected route: renders latest bot log content to web UI.
    Defers all bot identity and file lookup until runtime.
    """
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))

    log_content = ""
    try:
        bot_identity_string = load_bot_identity()
        validate_bot_identity(bot_identity_string)
        log_path = Path(get_output_path(bot_identity_string, "logs", "*.log"))

        if log_path.is_file():
            log_content = log_path.read_text(encoding="utf-8")
        else:
            log_content = "Log file not found."
            log_event("logs_web", f"Log file missing: {log_path}", level="warning")

    except Exception as e:
        log_content = f"[logs_web] Error loading logs: {e}"
        log_event("logs_web", f"Exception while loading logs: {e}", level="error")

    return render_template("logs.html", log_text=log_content)
