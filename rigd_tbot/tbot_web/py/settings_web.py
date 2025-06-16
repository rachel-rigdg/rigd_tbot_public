# tbot_web/py/settings_web.py
# Manages all trading strategy and runtime config variables (open/mid/close timings, analysis, monitoring, etc.) via web UI; excludes credentials

import sys
from flask import Blueprint, request, jsonify, render_template, abort, redirect, url_for
from tbot_web.py.login_web import login_required
from pathlib import Path
import tempfile
import os
import json

from tbot_bot.support.bootstrap_utils import is_first_bootstrap

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from tbot_bot.config.env_bot import get_bot_config, validate_bot_config
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import validate_bot_identity, get_bot_identity_string_regex
from tbot_bot.config.security_bot import encrypt_env_bot_from_bytes

settings_blueprint = Blueprint("settings_web", __name__)

SECTION_TITLES = {
    "General & Debugging": [
        "VERSION_TAG", "BUILD_MODE", "DISABLE_ALL_TRADES", "DEBUG_LOG_LEVEL", "ENABLE_LOGGING", "LOG_FORMAT"
    ],
    "Trade Execution & Risk Controls": [
        "TRADE_CONFIRMATION_REQUIRED", "API_RETRY_LIMIT", "API_TIMEOUT", "FRACTIONAL", "TOTAL_ALLOCATION",
        "MAX_TRADES", "WEIGHTS", "DAILY_LOSS_LIMIT", "MAX_RISK_PER_TRADE", "MAX_OPEN_POSITIONS"
    ],
    "Price & Volume Filters": [
        "MIN_PRICE", "MAX_PRICE", "MIN_VOLUME_THRESHOLD", "ENABLE_FUNNHUB_FUNDAMENTALS_FILTER",
        "MAX_PE_RATIO", "MAX_DEBT_EQUITY"
    ],
    "Strategy Routing & Broker Mode": [
        "STRATEGY_SEQUENCE", "STRATEGY_OVERRIDE"
    ],
    "Automated Rebalance Triggers": [
        "ACCOUNT_BALANCE", "REBALANCE_ENABLED", "REBALANCE_THRESHOLD", "REBALANCE_CHECK_INTERVAL"
    ],
    "Failover Broker Routing": [
        "FAILOVER_ENABLED", "FAILOVER_LOG_TAG"
    ],
    "Global Time & Polling": [
        "TRADING_DAYS", "SLEEP_TIME"
    ],
    "OPEN Strategy Configuration (20 min trading)": [
        "MAX_GAP_PCT_OPEN", "MIN_MARKET_CAP_OPEN", "MAX_MARKET_CAP_OPEN", "STRAT_OPEN_ENABLED",
        "START_TIME_OPEN", "OPEN_ANALYSIS_TIME", "OPEN_BREAKOUT_TIME", "OPEN_MONITORING_TIME",
        "STRAT_OPEN_BUFFER", "SHORT_TYPE_OPEN"
    ],
    "MID Strategy Configuration (VWAP Reversion)": [
        "MAX_GAP_PCT_MID", "MIN_MARKET_CAP_MID", "MAX_MARKET_CAP_MID", "STRAT_MID_ENABLED",
        "START_TIME_MID", "MID_ANALYSIS_TIME", "MID_BREAKOUT_TIME", "MID_MONITORING_TIME",
        "STRAT_MID_VWAP_THRESHOLD", "SHORT_TYPE_MID"
    ],
    "CLOSE Strategy Configuration (EOD Momentum/Fade)": [
        "MAX_GAP_PCT_CLOSE", "MIN_MARKET_CAP_CLOSE", "MAX_MARKET_CAP_CLOSE", "STRAT_CLOSE_ENABLED",
        "START_TIME_CLOSE", "CLOSE_ANALYSIS_TIME", "CLOSE_BREAKOUT_TIME", "CLOSE_MONITORING_TIME",
        "STRAT_CLOSE_VIX_THRESHOLD", "SHORT_TYPE_CLOSE"
    ],
    "Notifications": [
        "NOTIFY_ON_FILL", "NOTIFY_ON_EXIT"
    ],
    "Reporting & Ledger Export": [
        "LEDGER_EXPORT_MODE"
    ],
    "Defense Mode (Disaster Risk Reduction)": [
        "DEFENSE_MODE_ACTIVE", "DEFENSE_MODE_TRADE_LIMIT_PCT", "DEFENSE_MODE_TOTAL_ALLOCATION"
    ],
    "ENHANCEMENT MODULE TOGGLES": [
        "ENABLE_REBALANCE_NOTIFIER", "REBALANCE_TRIGGER_PCT", "RBAC_ENABLED", "DEFAULT_USER_ROLE",
        "ENABLE_STRATEGY_OPTIMIZER", "OPTIMIZER_BACKTEST_LOOKBACK_DAYS", "OPTIMIZER_ALGORITHM", "OPTIMIZER_OUTPUT_DIR",
        "ENABLE_SLIPPAGE_MODEL", "SLIPPAGE_SIMULATION_TYPE", "SLIPPAGE_MEAN_PCT", "SLIPPAGE_STDDEV_PCT", "SIMULATED_LATENCY_MS",
        "ENABLE_BSM_FILTER", "MAX_BSM_DEVIATION", "RISK_FREE_RATE", "RISK_FREE_RATE_SOURCE",
        "NOTIFY_ON_FAILURE", "CRITICAL_ALERT_CHANNEL", "ROUTINE_ALERT_CHANNEL"
    ]
}

def get_valid_bot_identity_string():
    try:
        # Always load the decrypted identity directly from the encrypted secret.
        identity = load_bot_identity()
        if identity and get_bot_identity_string_regex().match(identity):
            validate_bot_identity(identity)
            return identity
        return None
    except Exception:
        return None

@settings_blueprint.route("/settings")
@login_required
def settings_page():
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity:
            return render_template("settings.html", config=None, error="Bot identity not available, please complete configuration")
        config = get_bot_config()
    except Exception:
        return render_template("settings.html", config=None, error="Bot identity not available, please complete configuration")
    return render_template("settings.html", config=config, section_titles=SECTION_TITLES, error=None)

@settings_blueprint.route("/settings.json", methods=["GET"])
@login_required
def get_settings():
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity:
            return jsonify({"error": "Bot identity not available, please complete configuration"}), 400
        config = get_bot_config()
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": "Bot identity not available, please complete configuration"}), 400

@settings_blueprint.route("/settings/update", methods=["POST"])
@login_required
def update_settings():
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    if not request.is_json:
        return jsonify({"status": "error", "detail": "Invalid JSON body"}), 400
    try:
        data = request.get_json()
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity:
            return jsonify({"status": "error", "detail": "Bot identity not available, please complete configuration"}), 400
        validate_bot_config(data)
        raw_bytes = json.dumps(data, indent=2).encode("utf-8")
        encrypt_env_bot_from_bytes(raw_bytes, rotate_key=False)
        return jsonify({"status": "updated"})
    except Exception as e:
        return jsonify({"status": "error", "detail": "Bot identity not available, please complete configuration"}), 400

# Always validates using load_bot_identity(); config is only loaded after identity check.
