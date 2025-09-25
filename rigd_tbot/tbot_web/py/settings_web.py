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

from tbot_bot.config.env_bot import get_bot_config, validate_bot_config  # validate kept for compatibility (not enforced on save)
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import validate_bot_identity, get_bot_identity_string_regex
from tbot_bot.config.security_bot import encrypt_env_bot_from_bytes

# Import canonical config fetch and rotation helper
from tbot_bot.support.config_fetch import get_live_config_for_rotation
from tbot_bot.config.provisioning_helper import rotate_all_keys_and_secrets

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

# -------- NEW (surgical): compute "used keys" and coerce incoming values --------
def _all_config_keys_used_by_codebase():
    """
    Minimal allowlist of keys we know are consumed in code, used to flag 'unused' in UI.
    We flatten SECTION_TITLES and add a few cross-cutting settings referenced elsewhere.
    """
    used = set()
    for _, keys in SECTION_TITLES.items():
        used.update(keys)
    # Cross-cutting keys used by UI/ops
    used.update({
        "UNIVERSE_MIN_DISPLAY_WARN", "UNIVERSE_MIN_SIZE_WARN",
        "STRAT_OPEN_ENABLED", "STRAT_MID_ENABLED", "STRAT_CLOSE_ENABLED",
        "START_TIME_OPEN", "START_TIME_MID", "START_TIME_CLOSE",
        "OPEN_ANALYSIS_TIME", "MID_ANALYSIS_TIME", "CLOSE_ANALYSIS_TIME",
        "OPEN_BREAKOUT_TIME", "MID_BREAKOUT_TIME", "CLOSE_BREAKOUT_TIME",
        "OPEN_MONITORING_TIME", "MID_MONITORING_TIME", "CLOSE_MONITORING_TIME",
        "DISABLE_ALL_TRADES",
    })
    return sorted(used)

def _coerce_value(v):
    """
    Best-effort type coercion for posted settings:
      - 'true'/'false' → bool
      - numeric strings → int/float
      - leaves everything else as-is
    """
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    low = s.lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    # try int
    try:
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return int(s)
    except Exception:
        pass
    # try float
    try:
        return float(s)
    except Exception:
        return v

# -----------------------------------------------------------------------------

@settings_blueprint.route("/settings")
@login_required
def settings_page():
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity:
            return render_template("settings.html", config=None, error="Bot identity not available, please complete configuration")
        # NEW: load full decrypted config and compute unused keys
        cfg = get_bot_config() or {}
        used = set(_all_config_keys_used_by_codebase())
        unused = sorted([k for k in cfg.keys() if k not in used])
        # Keep legacy 'config' for templates; also pass 'cfg' and 'unused_keys' explicitly
        return render_template(
            "settings.html",
            config=cfg,
            cfg=cfg,
            section_titles=SECTION_TITLES,
            unused_keys=unused,
            error=None
        )
    except Exception:
        return render_template("settings.html", config=None, error="Bot identity not available, please complete configuration")

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
    """
    Accept and persist every posted key/value (do not drop unfamiliar keys).
    Type-coerce common primitives; merge into existing config; write via existing encryption path.
    """
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    if not request.is_json:
        return jsonify({"status": "error", "detail": "Invalid JSON body"}), 400
    try:
        data = request.get_json() or {}
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity:
            return jsonify({"status": "error", "detail": "Bot identity not available, please complete configuration"}), 400

        # Load current config and merge coerced updates
        current = get_bot_config() or {}
        coerced = {k: _coerce_value(v) for k, v in data.items()}
        current.update(coerced)

        # NOTE: We do NOT reject unknown keys; we persist everything posted.
        # If you still want to validate known keys, do it non-fatal:
        try:
            # This will validate known keys where supported; unknown keys are ignored by validator
            validate_bot_config({k: current[k] for k in _all_config_keys_used_by_codebase() if k in current})
        except Exception:
            # Do not block saving on validation of subset; per requirement, persist anyway.
            pass

        raw_bytes = json.dumps(current, indent=2).encode("utf-8")
        encrypt_env_bot_from_bytes(raw_bytes, rotate_key=False)

        # After successful settings update, rotate keys/secrets with canonical config (skip during first bootstrap)
        live_config = get_live_config_for_rotation()
        if live_config:
            rotate_all_keys_and_secrets(live_config)

        # Compute unused set for response (helps UI refresh without reloading page)
        used = set(_all_config_keys_used_by_codebase())
        unused = sorted([k for k in current.keys() if k not in used])

        return jsonify({"status": "updated", "unused_keys": unused})
    except Exception:
        return jsonify({"status": "error", "detail": "Bot identity not available, please complete configuration"}), 400

# Always validates using load_bot_identity(); config is only loaded after identity check.
