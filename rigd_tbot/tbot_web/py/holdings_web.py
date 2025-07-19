# tbot_web/py/holdings_web.py
# Flask blueprint: UI endpoints for holdings management, config, and status.

from flask import Blueprint, request, jsonify, render_template
from tbot_bot.config.env_bot import load_env_var, update_env_var
from tbot_bot.trading.holdings_utils import parse_etf_allocations, trigger_manual_rebalance

holdings_web = Blueprint("holdings_web", __name__)

@holdings_web.route("/", methods=["GET"])
def holdings_ui():
    return render_template("holdings.html")

@holdings_web.route("/holdings/config", methods=["GET"])
def get_holdings_config():
    return jsonify({
        "HOLDINGS_FLOAT_TARGET_PCT": load_env_var("HOLDINGS_FLOAT_TARGET_PCT", 10),
        "HOLDINGS_TAX_RESERVE_PCT": load_env_var("HOLDINGS_TAX_RESERVE_PCT", 20),
        "HOLDINGS_PAYROLL_PCT": load_env_var("HOLDINGS_PAYROLL_PCT", 10),
        "HOLDINGS_REBALANCE_INTERVAL": load_env_var("HOLDINGS_REBALANCE_INTERVAL", 6),
        "HOLDINGS_ETF_LIST": load_env_var("HOLDINGS_ETF_LIST", "SCHD:50,SCHY:50")
    })

@holdings_web.route("/holdings/config", methods=["POST"])
def update_holdings_config():
    data = request.json
    update_env_var("HOLDINGS_FLOAT_TARGET_PCT", data.get("HOLDINGS_FLOAT_TARGET_PCT"))
    update_env_var("HOLDINGS_TAX_RESERVE_PCT", data.get("HOLDINGS_TAX_RESERVE_PCT"))
    update_env_var("HOLDINGS_PAYROLL_PCT", data.get("HOLDINGS_PAYROLL_PCT"))
    update_env_var("HOLDINGS_REBALANCE_INTERVAL", data.get("HOLDINGS_REBALANCE_INTERVAL"))
    update_env_var("HOLDINGS_ETF_LIST", data.get("HOLDINGS_ETF_LIST"))
    return jsonify({"status": "success"})

@holdings_web.route("/holdings/status", methods=["GET"])
def get_holdings_status():
    return jsonify({
        "account_value": 100000,
        "cash": 9500,
        "etf_holdings": {"SCHD": 45500, "SCHY": 45000},
        "float_target": parse_etf_allocations(load_env_var("HOLDINGS_ETF_LIST", "")),
        "next_rebalance_due": "2025-12-31"
    })

@holdings_web.route("/holdings/rebalance", methods=["POST"])
def holdings_manual_rebalance():
    trigger_manual_rebalance()
    return jsonify({"status": "rebalance_triggered"})
