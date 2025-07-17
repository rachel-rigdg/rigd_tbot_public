# tbot_web/py/status_web.py

import json
from flask import Blueprint, render_template, jsonify
from .login_web import login_required
from tbot_bot.support.path_resolver import resolve_status_log_path
from pathlib import Path

status_blueprint = Blueprint("status_web", __name__)

@status_blueprint.route("/status")
@login_required
def status_page():
    """
    Loads bot status from JSON and renders to dashboard.
    Uses global status.json in tbot_bot/output/logs/status.json.
    """
    status_data = {}
    status_file_path = Path(resolve_status_log_path())

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

    # Patch: forcibly mirror bot_state.txt as "state" for live dashboard and JS updater
    bot_state_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
    try:
        bot_state_val = bot_state_path.read_text(encoding="utf-8").strip()
    except Exception:
        bot_state_val = "unknown"

    # Overwrite all keys named "state" and "bot_state" in status_data with live bot_state
    status_data["state"] = bot_state_val
    status_data["bot_state"] = bot_state_val

    return render_template("status.html", status=status_data)

@status_blueprint.route("/api/bot_state")
@login_required
def bot_state_api():
    status_file_path = Path(resolve_status_log_path())
    status_data = {}
    try:
        with open(status_file_path, "r", encoding="utf-8") as f:
            status_data = json.load(f)
    except Exception as e:
        status_data = {"error": str(e)}
    # Patch: always include 'bot_state' key as alias for .state for UI compatibility
    bot_state_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
    try:
        bot_state_val = bot_state_path.read_text(encoding="utf-8").strip()
    except Exception:
        bot_state_val = "unknown"
    status_data["state"] = bot_state_val
    status_data["bot_state"] = bot_state_val
    return jsonify(status_data)

@status_blueprint.route("/api/full_status")
@login_required
def full_status_api():
    status_file_path = Path(resolve_status_log_path())
    status_data = {}
    try:
        with open(status_file_path, "r", encoding="utf-8") as f:
            status_data = json.load(f)
    except Exception as e:
        status_data = {"error": str(e)}
    bot_state_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
    try:
        bot_state_val = bot_state_path.read_text(encoding="utf-8").strip()
    except Exception:
        bot_state_val = "unknown"
    status_data["state"] = bot_state_val
    status_data["bot_state"] = bot_state_val
    return jsonify(status_data)

@status_blueprint.route("/candidate_status")
@login_required
def candidate_status():
    """
    Loads and displays per-strategy candidate pool, fallback, and eligibility/rejection reasons.
    Reads session logs (SESSION_LOGS) or file at tbot_bot/output/logs/candidate_pool_status.json.
    """
    # This assumes strategy modules write all candidate attempts, reasons, etc. to a status log file.
    status_file_path = Path(__file__).resolve().parents[2] / "tbot_bot" / "output" / "logs" / "candidate_pool_status.json"
    candidate_data = []
    try:
        with open(status_file_path, "r", encoding="utf-8") as f:
            candidate_data = json.load(f)
    except FileNotFoundError:
        candidate_data = []
    except Exception as e:
        candidate_data = [{"error": f"Failed to load candidate pool log: {e}"}]

    # Render as simple table or raw JSON
    return render_template("candidate_status.html", candidate_status=candidate_data)
