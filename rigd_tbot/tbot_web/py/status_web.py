from __future__ import annotations
# tbot_web/py/status_web.py

import json
from datetime import datetime, timezone, date
from pathlib import Path

from flask import Blueprint, render_template, jsonify

from .login_web import login_required
from tbot_bot.support.path_resolver import (
    resolve_status_log_path,
    get_output_path,
    get_bot_state_path,
    get_schedule_json_path,
    # NEW helpers used for stamps/snapshots per MVP contract
    get_status_path,
    get_snapshot_path,
    get_stamp_path,
    get_bot_identity,
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
                # Legacy single holdings time (kept for back-compat)
                "holdings_utc": raw.get("holdings_utc", ""),
                # NEW: explicit holdings windows
                "holdings_open_utc": raw.get("holdings_open_utc", "") or raw.get("holdings_utc", ""),
                "holdings_mid_utc": raw.get("holdings_mid_utc", ""),
                "universe_utc": raw.get("universe_utc", ""),
                "holdings_after_open_min": raw.get("holdings_after_open_min", 10),
                "holdings_after_mid_min": raw.get("holdings_after_mid_min", raw.get("holdings_after_open_min", 10)),
                "universe_after_close_min": raw.get("universe_after_close_min", 120),
            }
            # Attach parsed instants (internal use)
            out["_dt_open"] = _parse_iso_utc(out["open_utc"])
            out["_dt_mid"] = _parse_iso_utc(out["mid_utc"])
            out["_dt_close"] = _parse_iso_utc(out["close_utc"])
            # Legacy alias + new parsed keys
            out["_dt_hold"] = _parse_iso_utc(out["holdings_utc"])
            out["_dt_hold_open"] = _parse_iso_utc(out["holdings_open_utc"])
            out["_dt_hold_mid"] = _parse_iso_utc(out["holdings_mid_utc"])
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
        "holdings_open_utc": "",
        "holdings_mid_utc": "",
        "universe_utc": "",
        "holdings_after_open_min": 10,
        "holdings_after_mid_min": 10,
        "universe_after_close_min": 120,
    }
    fallback["_dt_open"] = _parse_iso_utc(fallback["open_utc"])
    fallback["_dt_mid"] = _parse_iso_utc(fallback["mid_utc"])
    fallback["_dt_close"] = _parse_iso_utc(fallback["close_utc"])
    fallback["_dt_hold"] = None
    fallback["_dt_hold_open"] = None
    fallback["_dt_hold_mid"] = None
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

# ---------------------------
# NEW: Read-only helpers for MVP contract
# ---------------------------
def _read_opening_equity_stamp() -> dict:
    """
    Load {ts_utc, equity} from stamps/opening_equity.json
    """
    path = Path(get_stamp_path("opening_equity.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = (data.get("ts_utc") or "").strip()
        eq = data.get("equity")
        return {"ts_utc": ts or None, "equity": float(eq) if isinstance(eq, (int, float)) else None}
    except Exception:
        return {"ts_utc": None, "equity": None}

def _read_job_stamp(name: str) -> dict:
    """
    Parse one-line stamps like: "2025-09-18T21:05:00Z OK" or "… Failed"
    Returns {last_run_utc, status}
    """
    path = Path(get_stamp_path(name))
    try:
        line = path.read_text(encoding="utf-8").strip()
        if not line:
            return {"last_run_utc": None, "status": None}
        parts = line.split()
        ts = parts[0] if parts else None
        status = parts[1] if len(parts) > 1 else None
        return {"last_run_utc": ts, "status": status}
    except Exception:
        return {"last_run_utc": None, "status": None}

def _read_strategy_snapshot(kind: str) -> dict:
    """
    Load {ts_utc, candidates[], trades{}} from status/strategy_{kind}_last.json (truncate candidates to 5)
    """
    fname = f"strategy_{kind}_last.json"
    path = Path(get_snapshot_path(fname))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Normalize
        out = {
            "ts_utc": data.get("ts_utc") or None,
            "candidates": (data.get("candidates") or [])[:5],
            "trades": data.get("trades") or {"count": 0, "wins": 0, "losses": 0, "realized_pnl": 0.0},
        }
        return out
    except Exception:
        return {"ts_utc": None, "candidates": [], "trades": {"count": 0, "wins": 0, "losses": 0, "realized_pnl": 0.0}}

def _read_strategy_error(kind: str) -> str | None:
    """
    Read text from stamps/strategy_{kind}_error.txt, only if it's for TODAY (UTC).
    We accept either lines prefixed with ISO timestamp or plain message; when ts present, require same YYYY-MM-DD.
    """
    fname = f"strategy_{kind}_error.txt"
    path = Path(get_stamp_path(fname))
    try:
        txt = path.read_text(encoding="utf-8").strip()
        if not txt:
            return None
        # If first token is ISO timestamp, enforce today's date (UTC)
        first = txt.split()[0]
        today_utc = date.today()
        try:
            when = _parse_iso_utc(first)
            if when and when.date() != today_utc:
                return None
        except Exception:
            # no parsable timestamp; accept as-is
            pass
        return txt
    except Exception:
        return None

def _ledger_balances() -> dict:
    """
    Pull account equity/cash from authoritative ledger module (null-safe).
    Expected keys from module: as_of_utc, equity, cash, liabilities, nav
    """
    try:
        from tbot_bot.accounting.ledger_modules.ledger_balance import get_account_balances
        bal = get_account_balances() or {}
        out = {
            "as_of_utc": bal.get("as_of_utc") or None,
            "equity": float(bal.get("equity")) if bal.get("equity") is not None else None,
            "cash": float(bal.get("cash")) if bal.get("cash") is not None else None,
            "liabilities": float(bal.get("liabilities")) if bal.get("liabilities") is not None else None,
            "nav": float(bal.get("nav")) if bal.get("nav") is not None else None,
        }
        return out
    except Exception:
        return {"as_of_utc": None, "equity": None, "cash": None, "liabilities": None, "nav": None}

def _ledger_pnl() -> dict:
    """
    Pull realized PnL + win rates from ledger (zeros if none).
    """
    try:
        from tbot_bot.accounting.ledger_modules.ledger_query import get_pnl_summary
        p = get_pnl_summary() or {}
        return {
            "realized_today": float(p.get("realized_today") or 0.0),
            "realized_cumulative": float(p.get("realized_cumulative") or 0.0),
            "win_rate_today_pct": float(p.get("win_rate_today_pct") or 0.0),
            "win_rate_cumulative_pct": float(p.get("win_rate_cumulative_pct") or 0.0),
        }
    except Exception:
        return {
            "realized_today": 0.0,
            "realized_cumulative": 0.0,
            "win_rate_today_pct": 0.0,
            "win_rate_cumulative_pct": 0.0,
        }

def _resolve_strategy_states(schedule: dict, cfg_enabled: dict, active_strategy: str) -> dict:
    """
    Compute per-strategy state per rules:
      - if disabled flag false → state="disabled"
      - elif now < scheduled window start → state="scheduled"
      - elif active_strategy == kind → state="running"
      - elif today's error stamp exists → state="failed"
      - else → state="enabled"
    """
    now = datetime.now(timezone.utc)
    states = {}
    for kind in ("open", "mid", "close"):
        enabled = bool(cfg_enabled.get(kind))
        scheduled_key = f"{kind}_utc" if kind != "open" else "open_utc"
        scheduled_utc = (schedule or {}).get(scheduled_key) or None
        scheduled_dt = _parse_iso_utc(scheduled_utc) if scheduled_utc else None
        last_error = _read_strategy_error(kind)

        if not enabled:
            state = "disabled"
        elif scheduled_dt and now < scheduled_dt:
            state = "scheduled"
        elif active_strategy and active_strategy.lower() == kind:
            state = "running"
        elif last_error:
            state = "failed"
        else:
            state = "enabled"

        states[kind] = {
            "state": state,
            "scheduled_utc": scheduled_utc,
            "last_error": last_error,
        }
    return states

# ---------------------------
# Enrichment + API payload assembly
# ---------------------------
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
        enabled_flags = {
            "open": bool(cfg.get("STRAT_OPEN_ENABLED", False)),
            "mid": bool(cfg.get("STRAT_MID_ENABLED", False)),
            "close": bool(cfg.get("STRAT_CLOSE_ENABLED", False)),
        }
        enriched["enabled_strategies"] = enabled_flags
    except Exception:
        enabled_flags = enriched.get("enabled_strategies", {"open": False, "mid": False, "close": False})

    # ======== NEW: Contract fields ========
    identity = get_bot_identity() or ""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Account balances + PnL
    balances = _ledger_balances()
    pnl = _ledger_pnl()

    # Daily gain/loss via opening-equity stamp
    opening = _read_opening_equity_stamp()
    opening_equity = opening.get("equity")
    realized_equity_now = balances.get("equity")
    delta = (realized_equity_now - opening_equity) if (opening_equity is not None and realized_equity_now is not None) else None
    daily_gain_loss = {
        "opening_equity_utc": opening.get("ts_utc"),
        "opening_equity": opening_equity if opening_equity is not None else None,
        "realized_equity_now": realized_equity_now if realized_equity_now is not None else None,
        "delta": delta,
    }

    # Strategy states + last-run snapshots
    active_strategy = (enriched.get("active_strategy") or "none").lower()
    strategy_states = _resolve_strategy_states(schedule, enabled_flags, active_strategy)
    strategy_last_run = {
        "open": _read_strategy_snapshot("open"),
        "mid": _read_strategy_snapshot("mid"),
        "close": _read_strategy_snapshot("close"),
    }

    # Jobs (holdings manager, universe rebuild)
    jobs = {
        "holdings_manager": _read_job_stamp("holdings_manager_last.txt"),
        "universe_rebuild": _read_job_stamp("universe_rebuild_last.txt"),
    }

    # Risk controls (from config if present)
    max_risk = None
    daily_loss_limit = None
    try:
        max_risk = float(cfg.get("MAX_RISK_PER_TRADE")) if cfg.get("MAX_RISK_PER_TRADE") is not None else None
        daily_loss_limit = float(cfg.get("DAILY_LOSS_LIMIT")) if cfg.get("DAILY_LOSS_LIMIT") is not None else None
    except Exception:
        pass

    # Counters from existing fields (non-breaking)
    counters = {
        "trade_count": int(enriched.get("trade_count") or 0),
        "wins": int(enriched.get("win_trades") or 0),
        "losses": int(enriched.get("loss_trades") or 0),
        "error_count": int(enriched.get("error_count") or 0),
    }

    # Attach new contract fields
    enriched.update({
        "bot_identity": identity,
        "trading_date_utc": (enriched["schedule"].get("trading_date") or ""),
        "created_utc": now_utc,
        "timestamp_utc": now_utc,
        "account_balances": balances,
        "daily_gain_loss": daily_gain_loss,
        "pnl": pnl,
        "strategy_states": strategy_states,
        "strategy_last_run": strategy_last_run,
        "jobs": jobs,
        "risk_controls": {
            "max_risk_per_trade": max_risk,
            "daily_loss_limit": daily_loss_limit,
        },
        # Remap schedule keys for API contract aliases (non-breaking)
        "schedule_contract": {
            "open_utc": enriched["schedule"].get("open_utc") or "",
            "holdings_after_open_utc": enriched["schedule"].get("holdings_open_utc") or enriched["schedule"].get("holdings_utc") or "",
            "holdings_after_mid_utc": enriched["schedule"].get("holdings_mid_utc") or "",
            "mid_utc": enriched["schedule"].get("mid_utc") or "",
            "close_utc": enriched["schedule"].get("close_utc") or "",
            "universe_after_close_utc": enriched["schedule"].get("universe_utc") or "",
        },
    })
    # For compatibility, also expose the contract-shaped "schedule" without internal _dt_* keys.
    enriched["schedule"].update({
        "holdings_after_open_utc": enriched["schedule"].get("holdings_open_utc") or enriched["schedule"].get("holdings_utc") or "",
        "holdings_after_mid_utc": enriched["schedule"].get("holdings_mid_utc") or "",
        "universe_after_close_utc": enriched["schedule"].get("universe_utc") or "",
    })

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
    # Extended JSON including contract fields
    return jsonify(_enrich_status(_read_status_json()))

@status_blueprint.route("/api/full_status")
@login_required
def full_status_api():
    # Extended JSON including contract fields
    return jsonify(_enrich_status(_read_status_json()))
