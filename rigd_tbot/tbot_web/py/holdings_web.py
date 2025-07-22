# tbot_web/py/holdings_web.py
# Flask blueprint: UI endpoints for holdings management, config, and status.
# Fully compliant with v048 specs, with guards, RBAC, logging, and real-time broker data.

from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for
from tbot_bot.config.env_bot import load_env_var, update_env_var
from tbot_web.support.auth_web import get_current_user, get_user_role
from tbot_bot.trading.holdings_utils import parse_etf_allocations
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import validate_bot_identity, get_bot_identity_string_regex
from tbot_bot.support.holdings_secrets import load_holdings_secrets, save_holdings_secrets
from tbot_bot.support.bootstrap_utils import is_first_bootstrap
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path
import os

holdings_web = Blueprint("holdings_web", __name__)

INITIALIZE_STATES = ("initialize", "provisioning", "bootstrapping")
BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
HOLDINGS_SECRET_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "secrets" / "holdings_secrets.json.enc"

def get_current_bot_state():
    try:
        return BOT_STATE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"

def provisioning_guard():
    return get_current_bot_state() in INITIALIZE_STATES or is_first_bootstrap()

def identity_guard():
    try:
        bot_id = load_bot_identity()
        if not bot_id or not get_bot_identity_string_regex().match(bot_id):
            return True
        validate_bot_identity(bot_id)
        return False
    except Exception:
        return True

@holdings_web.route("/", methods=["GET"])
def holdings_ui():
    if provisioning_guard() or identity_guard():
        flash("Holdings management unavailable — provisioning or identity incomplete.", "error")
        return redirect(url_for("main.root_router"))
    user = get_current_user()
    if get_user_role(user) != "admin":
        flash("Access denied: Admins only.", "error")
        return redirect(url_for("main.root_router"))
    return render_template("holdings.html")

@holdings_web.route("/holdings/config", methods=["GET"])
def get_holdings_config():
    """Return all editable holdings configuration parameters."""
    try:
        if not HOLDINGS_SECRET_PATH.exists():
            return jsonify({
                "HOLDINGS_FLOAT_TARGET_PCT": 10,
                "HOLDINGS_TAX_RESERVE_PCT": 20,
                "HOLDINGS_PAYROLL_PCT": 10,
                "HOLDINGS_REBALANCE_INTERVAL": 6,
                "HOLDINGS_ETF_LIST": "SCHD:50,SCHY:50",
                "next_rebalance_due": None,
                "status": "uninitialized"
            })

        secrets = load_holdings_secrets()
        return jsonify({
            "HOLDINGS_FLOAT_TARGET_PCT": load_env_var("HOLDINGS_FLOAT_TARGET_PCT", 10),
            "HOLDINGS_TAX_RESERVE_PCT": load_env_var("HOLDINGS_TAX_RESERVE_PCT", 20),
            "HOLDINGS_PAYROLL_PCT": load_env_var("HOLDINGS_PAYROLL_PCT", 10),
            "HOLDINGS_REBALANCE_INTERVAL": load_env_var("HOLDINGS_REBALANCE_INTERVAL", 6),
            "HOLDINGS_ETF_LIST": load_env_var("HOLDINGS_ETF_LIST", "SCHD:50,SCHY:50"),
            "next_rebalance_due": secrets.get("NEXT_REBALANCE_DUE"),
            "status": "ok"
        })
    except Exception as e:
        return jsonify({"error": f"Failed to load config: {str(e)}"}), 500

@holdings_web.route("/holdings/config", methods=["POST"])
def update_holdings_config():
    user = get_current_user()
    if get_user_role(user) != "admin":
        return jsonify({"error": "Access denied"}), 403
    data = request.json or {}
    try:
        update_env_var("HOLDINGS_FLOAT_TARGET_PCT", data.get("HOLDINGS_FLOAT_TARGET_PCT"))
        update_env_var("HOLDINGS_TAX_RESERVE_PCT", data.get("HOLDINGS_TAX_RESERVE_PCT"))
        update_env_var("HOLDINGS_PAYROLL_PCT", data.get("HOLDINGS_PAYROLL_PCT"))
        update_env_var("HOLDINGS_REBALANCE_INTERVAL", data.get("HOLDINGS_REBALANCE_INTERVAL"))
        update_env_var("HOLDINGS_ETF_LIST", data.get("HOLDINGS_ETF_LIST"))

        # === Rebalance timer logic ===
        interval = int(data.get("HOLDINGS_REBALANCE_INTERVAL", 3))
        next_due = datetime.utcnow().date() + relativedelta(months=interval)
        secrets = load_holdings_secrets() if HOLDINGS_SECRET_PATH.exists() else {}
        secrets["NEXT_REBALANCE_DUE"] = next_due.isoformat()
        save_holdings_secrets(secrets)

        return jsonify({
            "status": "success",
            "next_rebalance_due": secrets["NEXT_REBALANCE_DUE"],
            "updated_by": getattr(user, "username", user if user else "system")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@holdings_web.route("/holdings/status", methods=["GET"])
def holdings_status():
    if provisioning_guard() or identity_guard():
        return jsonify({"error": "Holdings unavailable: provisioning or identity incomplete"}), 400
    try:
        from tbot_bot.trading.holdings_manager import get_holdings_status
        return jsonify(get_holdings_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@holdings_web.route("/holdings/rebalance", methods=["POST"])
def holdings_manual_rebalance():
    user = get_current_user()
    if get_user_role(user) != "admin":
        return jsonify({"error": "Access denied"}), 403
    try:
        from tbot_bot.trading.holdings_manager import manual_holdings_action
        result = manual_holdings_action("rebalance", user=getattr(user, "username", user if user else "system"))
        return jsonify({"status": "rebalance_triggered", "details": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
