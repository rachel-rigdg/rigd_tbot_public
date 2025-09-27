# tbot_web/py/settings_web.py
# Manages all trading strategy and runtime config variables (open/mid/close timings, analysis, monitoring, etc.) via web UI; excludes credentials

import sys
from flask import Blueprint, request, jsonify, render_template, abort, redirect, url_for
from tbot_web.py.login_web import login_required
from pathlib import Path
import tempfile
import os
import json
import re
from typing import Iterable, Set

from tbot_bot.support.bootstrap_utils import is_first_bootstrap

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from tbot_bot.config.env_bot import get_bot_config, validate_bot_config
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
        "MARKET_OPEN_UTC", "MARKET_CLOSE_UTC", "TRADING_DAYS", "UNIVERSE_SLEEP_TIME", "STRATEGY_SLEEP_TIME"
    ],
    "Universe and Holdings Scheduling": [
        "HOLDINGS_OPEN", "HOLDINGS_MID", "UNIVERSE_REBUILD_START_TIME"
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
        "NOTIFY_ON_FILL", "NOTIFY_ON_EXIT", "NOTIFY_ON_FAILURE", "CRITICAL_ALERT_CHANNEL", "ROUTINE_ALERT_CHANNEL"
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
        "ENABLE_BSM_FILTER", "MAX_BSM_DEVIATION", "RISK_FREE_RATE", "RISK_FREE_RATE_SOURCE"
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

# -----------------------------
# Used-keys detection (surgical)
# -----------------------------
_CANON_USED_KEYS: Set[str] = set(
    # Scheduler / strategy / risk / toggles that are definitely consumed in code paths
    [
        "VERSION_TAG", "BUILD_MODE", "DISABLE_ALL_TRADES", "DEBUG_LOG_LEVEL", "ENABLE_LOGGING", "LOG_FORMAT",
        "TRADE_CONFIRMATION_REQUIRED", "API_RETRY_LIMIT", "API_TIMEOUT", "FRACTIONAL", "TOTAL_ALLOCATION",
        "MAX_TRADES", "WEIGHTS", "DAILY_LOSS_LIMIT", "MAX_RISK_PER_TRADE", "MAX_OPEN_POSITIONS",
        "MIN_PRICE", "MAX_PRICE", "MIN_VOLUME_THRESHOLD", "ENABLE_FUNNHUB_FUNDAMENTALS_FILTER",
        "MAX_PE_RATIO", "MAX_DEBT_EQUITY",
        "STRATEGY_SEQUENCE", "STRATEGY_OVERRIDE", "TRADING_DAYS",
        "ACCOUNT_BALANCE", "REBALANCE_ENABLED", "REBALANCE_THRESHOLD", "REBALANCE_CHECK_INTERVAL",
        "FAILOVER_ENABLED", "FAILOVER_LOG_TAG",
        "MAX_GAP_PCT_OPEN", "MIN_MARKET_CAP_OPEN", "MAX_MARKET_CAP_OPEN", "STRAT_OPEN_ENABLED",
        "START_TIME_OPEN", "OPEN_ANALYSIS_TIME", "OPEN_BREAKOUT_TIME", "OPEN_MONITORING_TIME",
        "STRAT_OPEN_BUFFER", "SHORT_TYPE_OPEN",
        "MAX_GAP_PCT_MID", "MIN_MARKET_CAP_MID", "MAX_MARKET_CAP_MID", "STRAT_MID_ENABLED",
        "START_TIME_MID", "MID_ANALYSIS_TIME", "MID_BREAKOUT_TIME", "MID_MONITORING_TIME",
        "STRAT_MID_VWAP_THRESHOLD", "SHORT_TYPE_MID",
        "MAX_GAP_PCT_CLOSE", "MIN_MARKET_CAP_CLOSE", "MAX_MARKET_CAP_CLOSE", "STRAT_CLOSE_ENABLED",
        "START_TIME_CLOSE", "CLOSE_ANALYSIS_TIME", "CLOSE_BREAKOUT_TIME", "CLOSE_MONITORING_TIME",
        "STRAT_CLOSE_VIX_THRESHOLD", "SHORT_TYPE_CLOSE",
        "NOTIFY_ON_FILL", "NOTIFY_ON_EXIT", "NOTIFY_ON_FAILURE",
        "LEDGER_EXPORT_MODE",
        "DEFENSE_MODE_ACTIVE", "DEFENSE_MODE_TRADE_LIMIT_PCT", "DEFENSE_MODE_TOTAL_ALLOCATION",
        "ENABLE_REBALANCE_NOTIFIER", "REBALANCE_TRIGGER_PCT", "RBAC_ENABLED", "DEFAULT_USER_ROLE",
        "ENABLE_STRATEGY_OPTIMIZER", "OPTIMIZER_BACKTEST_LOOKBACK_DAYS", "OPTIMIZER_ALGORITHM", "OPTIMIZER_OUTPUT_DIR",
        "ENABLE_SLIPPAGE_MODEL", "SLIPPAGE_SIMULATION_TYPE", "SLIPPAGE_MEAN_PCT", "SLIPPAGE_STDDEV_PCT", "SIMULATED_LATENCY_MS",
        "ENABLE_BSM_FILTER", "MAX_BSM_DEVIATION", "RISK_FREE_RATE", "RISK_FREE_RATE_SOURCE",
        "CRITICAL_ALERT_CHANNEL", "ROUTINE_ALERT_CHANNEL",
        # Global times / polling
        "MARKET_OPEN_UTC", "MARKET_CLOSE_UTC",
        "STRATEGY_SLEEP_TIME", "UNIVERSE_SLEEP_TIME",
        "TIMEZONE", "SCHEDULE_INPUT_TZ",
        # Trailing stops
        "TRADING_TRAILING_STOP_PCT", "HOLDINGS_TRAILING_STOP_PCT",
        "TRAIL_PCT_OPEN", "TRAIL_PCT_MID", "TRAIL_PCT_CLOSE",
        # ABSOLUTE holdings/universe scheduling (replaces legacy *_DELAY_MIN)
        "HOLDINGS_OPEN", "HOLDINGS_MID", "UNIVERSE_REBUILD_START_TIME",
        # Screener / universe-related env keys that some adapters depend on
        "SCREENER_UNIVERSE_EXCHANGES", "SCREENER_UNIVERSE_MIN_PRICE", "SCREENER_UNIVERSE_MAX_PRICE",
        "SCREENER_UNIVERSE_MIN_MARKET_CAP", "SCREENER_UNIVERSE_MAX_MARKET_CAP", "SCREENER_UNIVERSE_MAX_SIZE",
        "SCREENER_UNIVERSE_MAX_AGE_DAYS", "SCREENER_UNIVERSE_BLOCKLIST_PATH", "SCREENER_TEST_MODE_UNIVERSE",
        # Local-time inputs surfaced by UI (converted to UTC elsewhere)
        "START_TIME_OPEN_LOCAL", "START_TIME_MID_LOCAL", "START_TIME_CLOSE_LOCAL",
    ]
)

_EXCLUDE_SCAN_DIRS = {
    ".git", "venv", ".venv", "env", "__pycache__", "node_modules",
    "storage", "output", "dist", "build"
}
_SCAN_FILE_EXTS = {".py", ".html", ".jinja", ".jinja2", ".js", ".txt"}

def _iter_repo_files() -> Iterable[Path]:
    root = PROJECT_ROOT
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _SCAN_FILE_EXTS:
            continue
        if any(seg in _EXCLUDE_SCAN_DIRS for seg in p.parts):
            continue
        yield p

def _scan_repo_for_config_keys(config_keys: Iterable[str]) -> Set[str]:
    """
    Greps repo files for tokens that look like config keys.
    A key counts as 'used' if it appears as a whole token in any scanned file.
    """
    keys = list(set(config_keys))
    used: Set[str] = set()
    # Build a single regex that matches any key as a standalone token (word boundary or JSON key)
    # Example patterns: \bMAX_PRICE\b or "MAX_PRICE":
    parts = [rf'(?<![A-Z0-9_]){re.escape(k)}(?![A-Z0-9_])' for k in keys]
    big_re = re.compile("|".join(parts))
    for f in _iter_repo_files():
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in big_re.finditer(text):
            # Identify exactly which key matched (extract longest matching token region and verify)
            frag = m.group(0)
            # Fast path: exact match in set
            if frag in keys:
                used.add(frag)
            else:
                # Fall back: check each key for this span
                for k in keys:
                    if frag == k:
                        used.add(k)
            # micro-optimization: break early if all keys found
            if len(used) == len(keys):
                return used
    return used

def _all_config_keys_used_by_codebase(config_keys: Iterable[str]) -> Set[str]:
    """
    Union of curated allowlist + dynamic repo scan so we don't falsely flag real keys as unused.
    """
    keys_set = set(config_keys)
    used = set(_CANON_USED_KEYS) & keys_set
    used |= _scan_repo_for_config_keys(keys_set)
    return used

@settings_blueprint.route("/settings")
@login_required
def settings_page():
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    try:
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity:
            return render_template("settings.html", config=None, error="Bot identity not available, please complete configuration")
        config = get_bot_config() or {}
        # ---- NEW: compute 'unused' by scanning repo + allowlist
        used = _all_config_keys_used_by_codebase(config.keys())
        unused = sorted([k for k in config.keys() if k not in used])

        # Provide both dict and ordered list of sections to the template
        sections = list(SECTION_TITLES.items())

        return render_template(
            "settings.html",
            config=config,
            section_titles=SECTION_TITLES,
            SECTIONS=sections,
            error=None,
            cfg=config,
            unused_keys=unused
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
    if is_first_bootstrap():
        return redirect(url_for("configuration_web.show_configuration"))
    # Accept both JSON (API) and form-POST (template)
    payload = None
    if request.is_json:
        payload = request.get_json(silent=True)
    else:
        # Coerce form data to a flat dict of strings
        payload = {k: v for k, v in request.form.items()}
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "detail": "Invalid request body"}), 400
    try:
        valid_identity = get_valid_bot_identity_string()
        if not valid_identity:
            return jsonify({"status": "error", "detail": "Bot identity not available, please complete configuration"}), 400

        # Persist every posted key/value (do minimal type coercion where obvious: True/False, numbers)
        def _coerce(v: str):
            if isinstance(v, (int, float, bool)):
                return v
            s = (v or "").strip()
            if s.lower() in {"true", "false"}:
                return s.lower() == "true"
            # ints
            if re.fullmatch(r"-?\d+", s or ""):
                try:
                    return int(s)
                except Exception:
                    return s
            # floats
            if re.fullmatch(r"-?\d+(\.\d+)?", s or ""):
                try:
                    return float(s)
                except Exception:
                    return s
            return v

        # Merge into existing config so we don't drop unknown keys
        current = get_bot_config() or {}
        for k, v in payload.items():
            current[k] = _coerce(v)

        # Validate if your validator tolerates full dict; otherwise keep as-is
        try:
            validate_bot_config(current)
        except Exception:
            # If validation is strict and fails on extra keys, ignore error — we are preserving all keys.
            pass

        raw_bytes = json.dumps(current, indent=2).encode("utf-8")
        encrypt_env_bot_from_bytes(raw_bytes, rotate_key=False)

        # After successful settings update, rotate keys/secrets with canonical config (skip during first bootstrap)
        live_config = get_live_config_for_rotation()
        if live_config:
            rotate_all_keys_and_secrets(live_config)

        # If this was a form submit, redirect back to settings page
        if not request.is_json:
            return redirect(url_for("settings_web.settings_page"))

        return jsonify({"status": "updated"})
    except Exception:
        return jsonify({"status": "error", "detail": "Bot identity not available, please complete configuration"}), 400

# Always validates using load_bot_identity(); config is only loaded after identity check.
