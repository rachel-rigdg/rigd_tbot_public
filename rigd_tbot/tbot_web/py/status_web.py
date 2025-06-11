# tbot_web/py/status_web.py

import json
from flask import Blueprint, render_template
from .login_web import login_required
from pathlib import Path
from tbot_bot.support.path_resolver import get_output_path, validate_bot_identity

status_blueprint = Blueprint("status", __name__)

@status_blueprint.route("/status")
@login_required
def status_page():
    """
    Loads bot status from JSON and renders to dashboard.
    Enforces win_rate and related stats per build spec.
    """
    status_data = {}
    try:
        # Resolve BOT_IDENTITY_STRING from .env_bot
        bot_env_path = Path("tbot_bot/.env_bot")
        bot_identity_string = "INVALID_IDENTITY"
        if bot_env_path.exists():
            with open(bot_env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("BOT_IDENTITY_STRING"):
                        bot_identity_string = line.split("=", 1)[1].strip()
                        break
        validate_bot_identity(bot_identity_string)

        # Dynamically resolve status.json path
        status_file_path = Path(get_output_path(bot_identity_string, "logs", "status.json"))

        with open(status_file_path, "r", encoding="utf-8") as f:
            status_data = json.load(f)

        # Enforce required fields as per spec
        status_data.setdefault("win_rate", 0.0)
        status_data.setdefault("win_trades", 0)
        status_data.setdefault("loss_trades", 0)
        status_data.setdefault("pnl", 0.0)
        status_data.setdefault("trade_count", 0)

    except FileNotFoundError:
        status_data = {"error": "Status file not found."}
    except json.JSONDecodeError:
        status_data = {"error": "Malformed status file."}
    except Exception as e:
        status_data = {"error": str(e)}

    return render_template("status.html", status=status_data)
