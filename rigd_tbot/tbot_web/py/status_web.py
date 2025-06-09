# tbot_web/py/status_web.py
# Serves real-time bot/session status, strategy state, live PnL, win-rate, float status, risk/defense mode, and system health (data from status.json and supporting modules) to frontend.

import json
from flask import Blueprint, render_template, redirect, url_for
from tbot_web.py.login_web import login_required
from pathlib import Path
from tbot_bot.support.path_resolver import get_output_path, validate_bot_identity
from tbot_web.py.bootstrap_utils import is_first_bootstrap

status_blueprint = Blueprint("status", __name__)

BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

def get_current_bot_state():
    try:
        with open(BOT_STATE_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "unknown"

@status_blueprint.route("/status")
@login_required
def status_page():
    """
    Loads bot status from JSON and renders to dashboard.
    Handles initialize/provisioning/bootstrapping states and error states for UI display.
    """
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))

    bot_state = get_current_bot_state()
    if bot_state in ("initialize", "provisioning", "bootstrapping"):
        # Pass through to UI to display configuration/provisioning info
        return render_template("wait.html", bot_state=bot_state)
    if bot_state in ("error", "shutdown_triggered"):
        # Show error or shutdown state explicitly
        return render_template("wait.html", bot_state=bot_state)

    status_data = {}
    try:
        bot_env_path = Path("tbot_bot/.env_bot")
        bot_identity_string = "INVALID_IDENTITY"
        if bot_env_path.exists():
            with open(bot_env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("BOT_IDENTITY_STRING"):
                        bot_identity_string = line.split("=", 1)[1].strip()
                        break
        validate_bot_identity(bot_identity_string)
        status_file_path = Path(get_output_path(bot_identity_string, "logs", "status.json"))
        with open(status_file_path, "r", encoding="utf-8") as f:
            status_data = json.load(f)
    except FileNotFoundError:
        status_data = {"error": "Status file not found."}
    except json.JSONDecodeError:
        status_data = {"error": "Malformed status file."}
    except Exception as e:
        status_data = {"error": str(e)}

    return render_template("status.html", status=status_data, bot_state=bot_state)
