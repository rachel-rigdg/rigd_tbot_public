# tbot_web/py/status_web.py

import json
from flask import Blueprint, render_template, jsonify
from .login_web import login_required
from pathlib import Path

status_blueprint = Blueprint("status_web", __name__)

@status_blueprint.route("/status")
@login_required
def status_page():
    """
    Loads bot status from JSON and renders to dashboard.
    Uses universal status.json in tbot_bot/output/logs/status.json.
    """
    status_data = {}
    status_file_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / "logs" / "status.json"
    try:
        with open(status_file_path, "r", encoding="utf-8") as f:
            status_data = json.load(f)
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

@status_blueprint.route("/api/bot_state")
@login_required
def bot_state_api():
    bot_state_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
    try:
        state = bot_state_path.read_text(encoding="utf-8").strip()
    except Exception:
        state = "unknown"
    return jsonify({"bot_state": state})
