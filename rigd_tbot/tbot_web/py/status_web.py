# tbot_web/py/status_web.py

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytz
from flask import Blueprint, render_template, jsonify

from .login_web import login_required
from tbot_bot.support.path_resolver import (
    resolve_status_log_path,
    get_output_path
)
# UTC schedule getters (runtime MUST read UTC-only keys)
from tbot_bot.config.env_bot import (
    get_open_time_utc,
    get_mid_time_utc,
    get_close_time_utc,
    get_market_close_utc,
    get_timezone as get_cfg_timezone,   # returns timezone name string for UI display only
)

status_blueprint = Blueprint("status_web", __name__)

CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
OPEN_STAMP = CONTROL_DIR / "last_strategy_open_utc.txt"
MID_STAMP = CONTROL_DIR / "last_strategy_mid_utc.txt"
CLOSE_STAMP = CONTROL_DIR / "last_strategy_close_utc.txt"


def _read_status_json():
    status_file_path = Path(resolve_status_log_path())
    try:
        with open(status_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("win_rate", 0.0)
        data.setdefault("win_trades", 0)
        data.setdefault("loss_trades", 0)
        data.setdefault("pnl", 0.0)
        data.setdefault("trade_count", 0)
        return data
    except FileNotFoundError:
        return {"error": "Status file not found."}
    except json.JSONDecodeError:
        return {"error": "Malformed status file."}
    except Exception as e:
        return {"error": str(e)}


def _read_bot_state() -> str:
    try:
        return BOT_STATE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def _read_iso_stamp(path: Path):
    if not path.exists():
        return None
    try:
        s = path.read_text(encoding="utf-8").strip()
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _hhmm_to_time(hhmm: str):
    h, m = map(int, hhmm.split(":"))
    return h, m


def _today_dt_for(hhmm: str) -> datetime:
    now = datetime.now(timezone.utc)
    h, m = _hhmm_to_time(hhmm)
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def _next_dt_for(hhmm: str) -> datetime:
    now = datetime.now(timezone.utc)
    today_dt = _today_dt_for(hhmm)
    return today_dt if today_dt >= now else today_dt + timedelta(days=1)


def _format_local(dt_utc: datetime, tz_name: str) -> str:
    try:
        tz = pytz.timezone(tz_name or "UTC")
    except Exception:
        tz = pytz.UTC
    return dt_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _badge_for(kind: str, stamp_path: Path, sched_hhmm: str, bot_state: str) -> str:
    """
    Returns one of:
      - "Ran @ HH:MMZ"
      - "Late Launch"
      - "Pending"
    """
    now = datetime.now(timezone.utc)
    stamp = _read_iso_stamp(stamp_path)
    if stamp and stamp.date() == now.date():
        return f"Ran @ {stamp.strftime('%H:%M')}Z"
    sched_today = _today_dt_for(sched_hhmm)
    grace = timedelta(seconds=300)
    if bot_state == "running" and now > (sched_today + grace):
        return "Late Launch"
    return "Pending"


def _enrich_status(base_status: dict) -> dict:
    # Bot state
    bot_state = _read_bot_state()
    base_status["state"] = bot_state
    base_status["bot_state"] = bot_state

    # Schedules (UTC-only for runtime), plus localized display for UI
    open_hhmm = (get_open_time_utc() or "13:30").strip()
    mid_hhmm = (get_mid_time_utc() or "16:00").strip()
    close_hhmm = (get_close_time_utc() or "19:45").strip()
    mclose_hhmm = (get_market_close_utc() or "21:00").strip()

    tz_name = get_cfg_timezone() or "UTC"

    schedules = {}
    for key, hhmm in {
        "open": open_hhmm,
        "mid": mid_hhmm,
        "close": close_hhmm,
        "market_close": mclose_hhmm,
    }.items():
        today_utc = _today_dt_for(hhmm)
        next_utc = _next_dt_for(hhmm)
        schedules[key] = {
            "today_utc": today_utc.strftime("%Y-%m-%dT%H:%MZ"),
            "today_local": _format_local(today_utc, tz_name),
            "next_utc": next_utc.strftime("%Y-%m-%dT%H:%MZ"),
            "next_local": _format_local(next_utc, tz_name),
        }

    base_status["timezone"] = tz_name
    base_status["schedules"] = schedules

    # Run badges for today based on stamps
    run_badges = {
        "open": _badge_for("open", OPEN_STAMP, open_hhmm, bot_state),
        "mid": _badge_for("mid", MID_STAMP, mid_hhmm, bot_state),
        "close": _badge_for("close", CLOSE_STAMP, close_hhmm, bot_state),
    }
    base_status["run_badges"] = run_badges

    return base_status


@status_blueprint.route("/status")
@login_required
def status_page():
    """
    Loads bot status from JSON and renders to dashboard.
    Surfaces bot_state, run badges (open/mid/close), next UTC/localized schedule times.
    """
    status_data = _enrich_status(_read_status_json())

    # Load candidate status data (if present)
    candidate_status_file = Path(get_output_path("logs", "candidate_pool_status.json"))
    try:
        with open(candidate_status_file, "r", encoding="utf-8") as f:
            candidate_data = json.load(f)
    except FileNotFoundError:
        candidate_data = []
    except Exception as e:
        candidate_data = [{"error": f"Failed to load candidate status: {e}"}]

    return render_template("status.html", status=status_data, candidate_status=candidate_data)


@status_blueprint.route("/api/bot_state")
@login_required
def bot_state_api():
    data = _enrich_status(_read_status_json())
    return jsonify(data)


@status_blueprint.route("/api/full_status")
@login_required
def full_status_api():
    data = _enrich_status(_read_status_json())
    return jsonify(data)

# Remove candidate_status endpoint; candidate data is now integrated into /status page
