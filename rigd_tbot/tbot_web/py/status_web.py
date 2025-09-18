# tbot_web/py/status_web.py

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, render_template, jsonify

from .login_web import login_required
from tbot_bot.support.path_resolver import (
    resolve_status_log_path,
    get_output_path,
    get_bot_state_path,
    get_schedule_json_path,
)
from tbot_bot.config.env_bot import (
    get_open_time_utc,
    get_mid_time_utc,
    get_close_time_utc,
    get_market_close_utc,
)
from tbot_bot.config.env_bot import get_bot_config  # <-- ensure enabled flags come from encrypted config

status_blueprint = Blueprint("status_web", __name__)

# ----- Defaults so UI never renders blank -----
DEFAULT_STATUS = {
    "state": "idle",
    "bot_state": "idle",
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "active_strategy": "none",
    "trade_count": 0,
    "win_trades": 0,
    "loss_trades": 0,
    "win_rate": 0.0,
    "pnl": 0.0,
    "error_count": 0,
    "version": "n/a",
    "enabled_strategies": {"open": False, "mid": False, "close": False},
    # supervisor-related defaults (UI banner + machine state)
    "supervisor_banner": "Supervisor not scheduled.",
    "supervisor_state": "not_scheduled",  # one of: not_scheduled|scheduled|launched|running|failed
}

def _read_status_json() -> dict:
    """
    Always return a fully-populated dict so templates have values (zeros/'none') even if file missing/malformed.
    """
    payload = dict(DEFAULT_STATUS)
    status_file_path = Path(resolve_status_log_path())
    try:
        with open(status_file_path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        # Merge with defaults; file values win
        payload.update({k: v for k, v in data.items() if v is not None})
    except Exception:
        # keep defaults
        pass
    return payload

def _read_bot_state() -> str:
    try:
        return Path(get_bot_state_path()).read_text(encoding="utf-8").strip() or "idle"
    except Exception:
        return "idle"

def _parse_iso_utc(s: str):
    if not s:
        return None
    try:
        s2 = s.strip()
        if s2.endswith("Z"):
            s2 = s2.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def _read_schedule():
    """
    Read logs/schedule.json; if absent, fall back to config HH:MM (UTC) for today.
    Returns dict with UTC strings the UI can render.
    """
    sched_path = Path(get_schedule_json_path())
    if sched_path.exists():
        try:
            raw = json.load(open(sched_path, "r", encoding="utf-8"))
            # Ensure string fields exist (UI-friendly)
            out = {
                "trading_date": raw.get("trading_date", ""),
                "created_at_utc": raw.get("created_at_utc", ""),
                "open_utc": raw.get("open_utc", ""),
                "mid_utc": raw.get("mid_utc", ""),
                "close_utc": raw.get("close_utc", ""),
                "holdings_utc": raw.get("holdings_utc", ""),
                "universe_utc": raw.get("universe_utc", ""),
                "holdings_after_open_min": raw.get("holdings_after_open_min", 10),
                "universe_after_close_min": raw.get("universe_after_close_min", 120),
            }
            # Attach parsed instants (internal use)
            out["_dt_open"] = _parse_iso_utc(out["open_utc"])
            out["_dt_mid"] = _parse_iso_utc(out["mid_utc"])
            out["_dt_close"] = _parse_iso_utc(out["close_utc"])
            out["_dt_hold"] = _parse_iso_utc(out["holdings_utc"])
            out["_dt_univ"] = _parse_iso_utc(out["universe_utc"])
            return out
        except Exception:
            pass

    # Fallback: build a minimal schedule for today using config HH:MM UTC (strings only)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    def _mk(hhmm: str) -> str:
        hhmm = (hhmm or "00:00").strip()
        return f"{today}T{hhmm}:00Z" if len(hhmm) == 5 else f"{today}T{hhmm}Z"

    open_hhmm = (get_open_time_utc() or "13:30").strip()
    mid_hhmm = (get_mid_time_utc() or "16:00").strip()
    close_hhmm = (get_close_time_utc() or "19:45").strip()

    fallback = {
        "trading_date": today,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "open_utc": _mk(open_hhmm),
        "mid_utc": _mk(mid_hhmm),
        "close_utc": _mk(close_hhmm),
        "holdings_utc": "",  # computed by supervisor; leave empty in fallback
        "universe_utc": "",
        "holdings_after_open_min": 10,
        "universe_after_close_min": 120,
    }
    fallback["_dt_open"] = _parse_iso_utc(fallback["open_utc"])
    fallback["_dt_mid"] = _parse_iso_utc(fallback["mid_utc"])
    fallback["_dt_close"] = _parse_iso_utc(fallback["close_utc"])
    fallback["_dt_hold"] = None
    fallback["_dt_univ"] = None
    return fallback

def _determine_current_phase(schedule: dict) -> str:
    if not schedule:
        return "unknown"
    now = datetime.now(timezone.utc)
    t_open = schedule.get("_dt_open")
    t_mid = schedule.get("_dt_mid")
    t_close = schedule.get("_dt_close")
    t_univ = schedule.get("_dt_univ")
    if not t_open or not t_mid or not t_close:
        return "unknown"
    if now < t_open:
        return "pre"
    if t_open <= now < t_mid:
        return "open"
    if t_mid <= now < t_close:
        return "mid"
    if t_close <= now and (not t_univ or now < t_univ):
        return "close"
    if t_univ and now >= t_univ:
        return "post"
    return "post"

def _compute_supervisor_banner(enriched: dict, schedule: dict) -> tuple[str, str]:
    """
    Derive supervisor_state + banner message from available data.
    Priority:
      1) If status.json already has explicit supervisor_state/supervisor_status, respect it.
      2) Else infer from schedule presence and bot_state.
    """
    # Accept either key written by tbot_supervisor/status_bot
    existing_state = (enriched or {}).get("supervisor_state", "") or (enriched or {}).get("supervisor_status", "")
    existing_state = existing_state.strip().lower()
    if existing_state in {"scheduled", "launched", "running", "failed"}:
        banner_map = {
            "scheduled": "Supervisor scheduled.",
            "launched": "Supervisor launched.",
            "running": "Supervisor running.",
            "failed": "Supervisor failed.",
        }
        return existing_state, banner_map[existing_state]

    # Inference path (unchanged)
    bot_state = (enriched or {}).get("bot_state", "idle")
    sched_exists = bool(schedule)
    if not sched_exists:
        return "not_scheduled", "Supervisor not scheduled."

    if bot_state in {"analyzing"}:
        return "launched", "Supervisor launched."
    if bot_state in {"trading", "updating", "running", "monitoring"}:
        return "running", "Supervisor running."
    if bot_state in {"error", "shutdown_triggered"}:
        return "failed", "Supervisor failed."
    return "scheduled", "Supervisor scheduled."


def _enrich_status(base_status: dict) -> dict:
    # Ensure baseline keys exist
    enriched = dict(DEFAULT_STATUS)
    enriched.update(base_status or {})
    # Bot state
    bot_state = _read_bot_state()
    enriched["state"] = bot_state
    enriched["bot_state"] = bot_state
    # Config (UTC HH:MM) for display fallback
    enriched["config_schedule_utc"] = {
        "open_hhmm": (get_open_time_utc() or "13:30").strip(),
        "mid_hhmm": (get_mid_time_utc() or "16:00").strip(),
        "close_hhmm": (get_close_time_utc() or "19:45").strip(),
        "market_close_hhmm": (get_market_close_utc() or "21:00").strip(),
    }
   # schedule + current_phase (existing)
    schedule = _read_schedule()
    enriched["schedule"] = {k: v for k, v in (schedule or {}).items() if not k.startswith("_dt_")}
    enriched["current_phase"] = _determine_current_phase(schedule)

    # supervisor banner/state (now also accepts supervisor_status), unchanged call:
    sup_state, sup_banner = _compute_supervisor_banner(enriched, schedule)
    enriched["supervisor_state"] = sup_state
    enriched["supervisor_banner"] = sup_banner

    # NEW: provide compact 'supervisor' object for JS badges
    sup = {"scheduled": None, "launched": None, "running": None, "failed": None,
           "scheduled_at": None, "launched_at": None}
    if sup_state == "scheduled":
        sup["scheduled"] = True
    elif sup_state == "launched":
        sup["launched"] = True
    elif sup_state == "running":
        sup["running"] = True
    elif sup_state == "failed":
        sup["failed"] = True

    # optional timestamps (use schedule.created_at_utc for scheduled_at)
    if enriched["schedule"].get("created_at_utc"):
        sup["scheduled_at"] = enriched["schedule"]["created_at_utc"]
    # if supervisor wrote supervisor_updated_at into status.json, surface it
    if base_status and base_status.get("supervisor_updated_at"):
        sup["launched_at"] = base_status["supervisor_updated_at"]

    enriched["supervisor"] = sup

    # --- FIX: source strategy enabled flags from encrypted config (not stale status.json defaults) ---
    try:
        cfg = get_bot_config() or {}
        enriched["enabled_strategies"] = {
            "open": bool(cfg.get("STRAT_OPEN_ENABLED", False)),
            "mid": bool(cfg.get("STRAT_MID_ENABLED", False)),
            "close": bool(cfg.get("STRAT_CLOSE_ENABLED", False)),
        }
    except Exception:
        # keep whatever was present (defaults already false)
        pass

    return enriched

@status_blueprint.route("/status")
@login_required
def status_page():
    status_data = _enrich_status(_read_status_json())
    # Candidate status (optional)
    candidate_status_file = Path(get_output_path("logs", "candidate_pool_status.json"))
    try:
        with open(candidate_status_file, "r", encoding="utf-8") as f:
            candidate_data = json.load(f)
    except FileNotFoundError:
        candidate_data = []
    except Exception as e:
        candidate_data = [{"error": f"Failed to load candidate status: {e}"}]
    schedule = status_data.get("schedule")
    return render_template("status.html", status=status_data, candidate_status=candidate_data, schedule=schedule)

@status_blueprint.route("/api/bot_state")
@login_required
def bot_state_api():
    return jsonify(_enrich_status(_read_status_json()))

@status_blueprint.route("/api/full_status")
@login_required
def full_status_api():
    return jsonify(_enrich_status(_read_status_json()))
