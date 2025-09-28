# tbot_bot/runtime/tbot_supervisor.py
# Thin supervisor: computes today's UTC schedule from env_bot (already UTC),
# writes schedule.json, updates status/lock, spawns schedule_dispatcher, and exits.

# --- PATH BOOTSTRAP (must be first) ---
import sys as _sys, pathlib as _pathlib
_THIS_FILE = _pathlib.Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[2]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))
# --- END PATH BOOTSTRAP ---

import os
import sys
import json
import shlex
import datetime
from pathlib import Path
from typing import Dict, Tuple

# (surgical) strict UTC-time helpers (no DST on UTC)
from tbot_bot.support.utils_time import (
    now_utc,
    fmt_iso_utc,
    scheduled_run_utc,
)

# --- Paths & constants ---
ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"

# status & schedule live under output/logs via path_resolver
def _get_output_path(category: str, filename: str) -> Path:
    from tbot_bot.support.path_resolver import get_output_path
    p = Path(get_output_path(category=category, filename=filename))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

STATUS_PATH = _get_output_path("logs", "status.json")
SCHEDULE_PATH = _get_output_path("logs", "schedule.json")

def _iso_utc_now() -> str:
    # absolute UTC, never DST-shifted
    return fmt_iso_utc(now_utc())

def _write_log(line: str) -> None:
    log_path = _get_output_path("logs", "supervisor.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{_iso_utc_now()} [tbot_supervisor] {line}\n")

def _write_status(extra: Dict) -> None:
    payload = {}
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
    except Exception:
        payload = {}
    payload.update(extra or {})
    payload["supervisor_updated_at"] = _iso_utc_now()
    try:
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
    except Exception as e:
        _write_log(f"[status] write error: {e}")

def _write_bot_state(state: str) -> None:
    (CONTROL_DIR).mkdir(parents=True, exist_ok=True)
    (CONTROL_DIR / "bot_state.txt").write_text(state.strip() + "\n", encoding="utf-8")

def _get_times() -> Tuple[str, str, str, str, str, str, str]:
    """
    Pull UTC HH:MM baselines and absolute UTC HH:MM for holdings & universe,
    using new absolute scheduling keys (no legacy minute offsets).
    """
    from tbot_bot.config import env_bot

    # Strategy baselines (UTC HH:MM strings)
    open_utc = env_bot.get_open_time_utc()
    mid_utc = env_bot.get_mid_time_utc()
    close_utc = env_bot.get_close_time_utc()
    market_close_utc = env_bot.get_market_close_utc()

    # Absolute UTC HH:MM for holdings/universe
    holdings_open_hhmm = env_bot.get_holdings_open_utc()
    holdings_mid_hhmm = env_bot.get_holdings_mid_utc()
    universe_hhmm = env_bot.get_universe_rebuild_start_utc()

    return (
        open_utc, mid_utc, close_utc, market_close_utc,
        holdings_open_hhmm, holdings_mid_hhmm, universe_hhmm
    )
def _mk_utc_dt(anchor_date: datetime.date, hhmm_or_hhmmss: str) -> datetime.datetime:
    """
    Accepts 'HH:MM' or 'HH:MM:SS'. Rounds seconds to nearest minute (>=30s rounds up),
    and carries over to the next hour/day when needed. UTC only.
    """
    s = (hhmm_or_hhmmss or "00:00").strip()
    parts = s.split(":")
    if len(parts) == 2:
        hh, mm = int(parts[0]), int(parts[1])
        return datetime.datetime(anchor_date.year, anchor_date.month, anchor_date.day, hh, mm,
                                 tzinfo=datetime.timezone.utc)
    elif len(parts) == 3:
        hh, mm, ss = int(parts[0]), int(parts[1]), int(parts[2])
        # round to nearest minute
        if ss >= 30:
            mm += 1
            if mm == 60:
                mm = 0
                hh += 1
                if hh == 24:
                    anchor_date = anchor_date + datetime.timedelta(days=1)
                    hh = 0
        return datetime.datetime(anchor_date.year, anchor_date.month, anchor_date.day, hh, mm,
                                 tzinfo=datetime.timezone.utc)
    else:
        raise ValueError(f"Bad time format (expected 'HH:MM' or 'HH:MM:SS'): {hhmm_or_hhmmss!r}")


def _compute_schedule() -> Dict:
    """
    Build absolute UTC instants for the **current trading day** when possible.
    - If today is a trading day (per _is_non_trading_day), schedule for today.
    - Else, roll forward to the next trading day and schedule there.
    Always returns a schedule (so status can show something immediately).
    No local/DST math — UTC only.
    """
    (open_hhmm, mid_hhmm, close_hhmm, market_close_hhmm,
     hold_open_hhmm, hold_mid_hhmm, universe_hhmm) = _get_times()

    # Decide the anchor date: today if trading, else next trading day
    today = now_utc().date()
    skip_today, _reason = _is_non_trading_day(today)
    if not skip_today:
        anchor = today
    else:
        # simple roll-forward until a trading day is found
        anchor = today
        while True:
            anchor = anchor + datetime.timedelta(days=1)
            s, _ = _is_non_trading_day(anchor)
            if not s:
                break

    # Absolute UTC datetimes on the anchor date
    open_at         = _mk_utc_dt(anchor, open_hhmm)
    mid_at          = _mk_utc_dt(anchor, mid_hhmm)
    close_at        = _mk_utc_dt(anchor, close_hhmm)
    holdings_open_at= _mk_utc_dt(anchor, hold_open_hhmm)
    holdings_mid_at = _mk_utc_dt(anchor, hold_mid_hhmm)
    universe_at     = _mk_utc_dt(anchor, universe_hhmm)

    return {
        "trading_date": anchor.isoformat(),
        "created_at_utc": _iso_utc_now(),
        "open_utc": fmt_iso_utc(open_at),
        "mid_utc": fmt_iso_utc(mid_at),
        "close_utc": fmt_iso_utc(close_at),
        "market_close_utc_hint": market_close_hhmm,  # informational only
        "holdings_open_utc": fmt_iso_utc(holdings_open_at),
        "holdings_mid_utc": fmt_iso_utc(holdings_mid_at),
        "holdings_utc": fmt_iso_utc(holdings_open_at),  # back-compat alias
        "universe_utc": fmt_iso_utc(universe_at),
    }


def _supervisor_lock(trading_date: str) -> Path:
    p = _get_output_path("locks", f"supervisor_{trading_date}.lock")
    return p

def _spawn_dispatcher() -> int:
    import subprocess
    py = os.environ.get("TBOT_PY", sys.executable)
    cmd = f"{shlex.quote(py)} -m tbot_bot.runtime.schedule_dispatcher"
    _write_log(f"Spawning schedule_dispatcher: {cmd}")
    try:
        env = os.environ.copy()
        # ensure repo on child path
        repo = str(ROOT_DIR)
        cur = env.get("PYTHONPATH", "")
        if repo not in cur.split(os.pathsep):
            env["PYTHONPATH"] = f"{repo}{os.pathsep}{cur}" if cur else repo
        p = subprocess.Popen(shlex.split(cmd), cwd=str(ROOT_DIR), env=env)
        _write_log(f"schedule_dispatcher PID={p.pid}")
        return 0
    except Exception as e:
        _write_log(f"[spawn] error: {e}")
        return 1

# ---------- Holiday / Non-trading-day helpers (minimal, no redundancy) ----------
def _get_trading_day_set() -> set:
    """Parse env trading days like 'mon,tue,wed,thu,fri' into a set."""
    try:
        from tbot_bot.config.env_bot import get_trading_days
        raw = (get_trading_days() or "").strip().lower()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return set(parts) or {"mon", "tue", "wed", "thu", "fri"}
    except Exception:
        return {"mon", "tue", "wed", "thu", "fri"}

def _weekday_name(dt: datetime.date) -> str:
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][dt.weekday()]

def _load_holiday_set() -> set:
    """
    Optional file: tbot_bot/control/market_holidays.txt
    Format: one YYYY-MM-DD per line; '#' comments allowed.
    """
    holidays = set()
    try:
        fp = CONTROL_DIR / "market_holidays.txt"
        if not fp.exists():
            return holidays
        for line in fp.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                datetime.date.fromisoformat(s)
                holidays.add(s)
            except Exception:
                continue
    except Exception:
        pass
    return holidays

def _is_non_trading_day(d: datetime.date) -> Tuple[bool, str]:
    """
    Returns (True, reason) if date should be skipped due to weekend/non-trading day or holiday.
    """
    dayname = _weekday_name(d)
    allowed = _get_trading_day_set()
    if dayname not in allowed:
        return True, f"Non-trading day ({dayname})"
    holidays = _load_holiday_set()
    if d.isoformat() in holidays:
        return True, "Holiday (in market_holidays.txt)"
    return False, ""

# -------------------------------------------------------------------------------

def main() -> int:
    _write_bot_state("analyzing")
    _write_log("Supervisor start (thin mode)")
    _write_status({"supervisor_status": "launched", "supervisor_message": "Supervisor launched."})

    try:
        schedule = _compute_schedule()
        with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
            json.dump(schedule, f, indent=2, sort_keys=True)
        _write_log(f"Schedule written: {json.dumps(schedule, sort_keys=True)}")
        _write_status({"supervisor_status": "scheduled", "schedule": schedule})
    except Exception as e:
        _write_log(f"[schedule] ERROR {e}")
        _write_bot_state("error")
        _write_status({"supervisor_status": "failed", "supervisor_message": f"Schedule error: {e}"})
        return 1

    # Holiday / non-trading-day skip BEFORE lock/dispatcher
    trading_date = schedule["trading_date"]
    try:
        d = datetime.date.fromisoformat(trading_date)
        skip, reason = _is_non_trading_day(d)
        if skip:
            _write_log(f"Skipping dispatcher for {trading_date}: {reason}")
            _write_bot_state("idle")
            _write_status({
                "supervisor_status": "skipped",
                "supervisor_message": f"Supervisor skipped {trading_date}: {reason}.",
                "trading_date": trading_date,
                "skip_reason": reason
            })
            return 0
    except Exception as e:
        _write_log(f"[holiday-skip] WARNING could not evaluate holiday/non-trading day: {e}")

    lk = _supervisor_lock(trading_date)
    if not lk.exists():
        try:
            lk.write_text(_iso_utc_now() + "\n", encoding="utf-8")
        except Exception as e:
            _write_log(f"[lock] WARN could not write lock: {e}")  # non-fatal

    rc = _spawn_dispatcher()
    if rc == 0:
        _write_status({"supervisor_status": "running", "supervisor_message": "Dispatcher spawned."})
        _write_bot_state("monitoring")  # dispatcher will set concrete phase states as it runs
    else:
        _write_bot_state("error")
        _write_status({"supervisor_status": "failed", "supervisor_message": "Failed to spawn dispatcher."})
    return rc

if __name__ == "__main__":
    sys.exit(main())
