# tbot_bot/reporting/status_logger.py
# Writes status.json for archival/accounting summary only (never logs/status.json)
# MUST ONLY BE LAUNCHED BY tbot_supervisor.py. Direct execution by CLI, main.py, or any other process is forbidden.
# --------------------------------------------------

import sys

if __name__ == "__main__":
    print("[status_logger.py] Direct execution is not permitted. This module must only be launched by tbot_supervisor.py.")
    sys.exit(1)

import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbot_bot.runtime.status_bot import bot_status
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import resolve_status_summary_path, get_bot_identity
from tbot_bot.config.env_bot import (
    get_open_time_utc,
    get_mid_time_utc,
    get_close_time_utc,
)
from datetime import datetime, timezone
print(f"[LAUNCH] status_logger.py launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)

BOT_IDENTITY = get_bot_identity()
SUMMARY_STATUS_FILE = resolve_status_summary_path(BOT_IDENTITY)

# Control/stamps directory (keep resolver usage elsewhere unchanged)
CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"
OPEN_STAMP  = CONTROL_DIR / "last_strategy_open_utc.txt"
MID_STAMP   = CONTROL_DIR / "last_strategy_mid_utc.txt"
CLOSE_STAMP = CONTROL_DIR / "last_strategy_close_utc.txt"

GRACE_SEC = 300  # ±300s window


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


def _hhmm_today_utc(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    now = datetime.now(timezone.utc)
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def _emit_once(tag: str, strategy: str, msg: str):
    """Emit a log_event only once per UTC day per tag/strategy."""
    today_key = datetime.now(timezone.utc).strftime("%Y%m%d")
    flag = CONTROL_DIR / f"emitted_{tag}_{strategy}_{today_key}.flag"
    if flag.exists():
        return
    try:
        log_event("status_logger", msg)
        flag.write_text("1", encoding="utf-8")
    except Exception:
        # Do not raise — best-effort logging
        pass


def _check_schedule(strategy: str, sched_hhmm: str, stamp_path: Path):
    """
    Emit explicit events:
      - window opened
      - launched on time
      - late launch
      - missed schedule
      - per-day guard prevented relaunch
    """
    if not sched_hhmm:
        return

    now = datetime.now(timezone.utc)
    sched = _hhmm_today_utc(sched_hhmm)
    stamp = _read_iso_stamp(stamp_path)

    # Window opened (first time we cross scheduled time)
    if now >= sched and (now - sched) <= timedelta(seconds=GRACE_SEC):
        _emit_once("window_opened", strategy, f"{strategy}: window opened @ {sched.strftime('%H:%M')}Z")

    if stamp and stamp.date() == now.date():
        # Launched on time (within ±GRACE_SEC)
        if abs((stamp - sched).total_seconds()) <= GRACE_SEC:
            _emit_once(
                "launched_on_time",
                strategy,
                f"{strategy}: launched on time (scheduled {sched.strftime('%H:%M')}Z, actual {stamp.strftime('%H:%M')}Z)"
            )
        # Late launch
        elif (stamp - sched).total_seconds() > GRACE_SEC:
            _emit_once(
                "late_launch",
                strategy,
                f"{strategy}: late launch (scheduled {sched.strftime('%H:%M')}Z, actual {stamp.strftime('%H:%M')}Z)"
            )

        # Guard prevented relaunch (we are at/after schedule today and a stamp already exists)
        if now >= sched and (now - sched) <= timedelta(minutes=10):
            _emit_once(
                "guard_prevented",
                strategy,
                f"{strategy}: per-day guard prevented relaunch (stamp already exists for today)"
            )
    else:
        # Missed schedule: grace window passed with no stamp
        if now > (sched + timedelta(seconds=GRACE_SEC)):
            _emit_once(
                "missed_schedule",
                strategy,
                f"{strategy}: missed scheduled launch (scheduled {sched.strftime('%H:%M')}Z, no launch stamp found)"
            )


def write_status():
    """Serializes the current bot_status into JSON for archival/accounting summary only and emits schedule events."""
    status_data = bot_status.to_dict()
    status_data["written_at"] = datetime.utcnow().isoformat()

    # Force state to match bot_state.txt on disk (always freshest)
    try:
        bot_state_path = CONTROL_DIR / "bot_state.txt"
        if bot_state_path.exists():
            status_data["state"] = bot_state_path.read_text(encoding="utf-8").strip()
        else:
            status_data["state"] = "unknown"
    except Exception:
        status_data["state"] = "unknown"

    # Emit explicit scheduling events based on stamps vs. UTC schedule
    try:
        _check_schedule("open",  get_open_time_utc(),  OPEN_STAMP)
        _check_schedule("mid",   get_mid_time_utc(),   MID_STAMP)
        _check_schedule("close", get_close_time_utc(), CLOSE_STAMP)
    except Exception:
        # Never block status writing due to event emission
        pass

    os.makedirs(os.path.dirname(SUMMARY_STATUS_FILE), exist_ok=True)
    try:
        with open(SUMMARY_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2)
        log_event("status_logger", f"Status written to {SUMMARY_STATUS_FILE}")
    except Exception as e:
        log_event("status_logger", f"Failed to write status.json to {SUMMARY_STATUS_FILE}: {e}")
