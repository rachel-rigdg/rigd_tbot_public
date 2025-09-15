# tbot_bot/runtime/tbot_supervisor.py
# Daily one-shot supervisor: computes today's UTC schedule from env_bot (already UTC),
# writes schedule.json, runs phases sequentially, honors control flags between phases,
# routes stdout/stderr to per-phase logs, updates bot_state, and exits. No daemon loop.

import os
import sys
import json
import shlex
import time
import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# --- Paths & constants (no hardcoded cwd assumptions) ---
ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
CONTROL_STOP_FLAG = CONTROL_DIR / "control_stop.flag"
CONTROL_KILL_FLAG = CONTROL_DIR / "control_kill.flag"

# --- Lightweight helpers (preserve unrelated functionality elsewhere) ---

def _iso_utc_now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def _path_resolver_get(category: str, filename: str) -> Path:
    from tbot_bot.support.path_resolver import get_output_path
    p = Path(get_output_path(category=category, filename=filename))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _write_log(line: str) -> None:
    try:
        log_path = _path_resolver_get("logs", "supervisor.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{_iso_utc_now()} [tbot_supervisor] {line}\n")
    except Exception:
        # last-ditch
        print(f"{_iso_utc_now()} [tbot_supervisor] {line}", flush=True)

# ---- Status helpers (status.json in tbot_bot/output/logs) ----

def _status_path() -> Path:
    return _path_resolver_get("logs", "status.json")

def _read_status() -> Dict:
    try:
        with open(_status_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _write_status(payload: Dict) -> None:
    payload = dict(payload or {})
    payload["supervisor_updated_at"] = _iso_utc_now()
    with open(_status_path(), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

def _status_update(state: str, message: str = None, extra: Dict = None) -> None:
    data = _read_status()
    data["supervisor_status"] = str(state)
    if message is not None:
        data["supervisor_message"] = str(message)
    if isinstance(extra, dict):
        data.update(extra)
    try:
        _write_status(data)
    except Exception as e:
        _write_log(f"[status] ERROR writing status.json: {e}")

def _write_state(state: str) -> None:
    try:
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        BOT_STATE_PATH.write_text(state.strip() + "\n", encoding="utf-8")
    except Exception as e:
        _write_log(f"[write_state] ERROR {e}")

def _parse_hhmm_utc(hhmm: str) -> Tuple[int, int]:
    hh, mm = str(hhmm).strip().split(":")
    return int(hh), int(mm)

def _today_utc_at(hour: int, minute: int) -> datetime.datetime:
    d = datetime.datetime.utcnow().date()
    return datetime.datetime(d.year, d.month, d.day, hour, minute, tzinfo=datetime.timezone.utc)

def _sleep_until(ts: datetime.datetime) -> None:
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        remaining = (ts - now).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60))

def _flag_requested() -> Optional[str]:
    if CONTROL_KILL_FLAG.exists():
        return "kill"
    if CONTROL_STOP_FLAG.exists():
        return "stop"
    return None

def _phase_log_path(phase: str) -> Path:
    return _path_resolver_get("logs", f"{phase}.log")

def _schedule_path() -> Path:
    return _path_resolver_get("logs", "schedule.json")

def _lock_path(trading_date: str) -> Path:
    return _path_resolver_get("locks", f"supervisor_{trading_date}.lock")

def _write_schedule_json(payload: Dict) -> None:
    with open(_schedule_path(), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

def _run_worker(cmd: str, log_path: Path) -> int:
    _write_log(f"Exec: {cmd}")
    import subprocess
    with open(log_path, "ab", buffering=0) as lf:
        try:
            p = subprocess.Popen(
                shlex.split(cmd),
                cwd=str(ROOT_DIR),
                stdout=lf,
                stderr=lf,
                env=os.environ.copy()
            )
            rc = p.wait()
            _write_log(f"Exit {rc}: {cmd}")
            return int(rc)
        except Exception as e:
            msg = f"[run_worker] ERROR executing '{cmd}': {e}"
            _write_log(msg)
            try:
                lf.write((msg + "\n").encode("utf-8", errors="ignore"))
            except Exception:
                pass
            return 1

def _phase_boundary_check() -> Optional[str]:
    flag = _flag_requested()
    if flag == "kill":
        _write_state("shutdown_triggered")
        _write_log("Kill flag detected. Aborting remaining phases.")
        return "kill"
    if flag == "stop":
        _write_state("graceful_closing_positions")
        _write_log("Stop flag detected. Halting further phases gracefully.")
        return "stop"
    return None

# --- Env getters (use existing env_bot; no local/DST math here) ---

def _get_times_and_delays() -> Tuple[str, str, str, str, int, int]:
    from tbot_bot.config import env_bot
    open_utc = env_bot.get_open_time_utc()
    mid_utc = env_bot.get_mid_time_utc()
    close_utc = env_bot.get_close_time_utc()
    market_close_utc = env_bot.get_market_close_utc()
    sup_open_delay_min = env_bot.get_sup_open_delay_min()      # default 10
    sup_uni_after_close_min = env_bot.get_sup_universe_after_close_min()  # default 120
    return open_utc, mid_utc, close_utc, market_close_utc, sup_open_delay_min, sup_uni_after_close_min

def _compute_schedule() -> Dict:
    open_hhmm, mid_hhmm, close_hhmm, market_close_hhmm, sup_open_delay_min, sup_uni_after_close_min = _get_times_and_delays()

    oh, om = _parse_hhmm_utc(open_hhmm)
    mh, mm = _parse_hhmm_utc(mid_hhmm)
    ch, cm = _parse_hhmm_utc(close_hhmm)

    open_at = _today_utc_at(oh, om)
    mid_at = _today_utc_at(mh, mm)
    close_at = _today_utc_at(ch, cm)

    holdings_at = open_at + datetime.timedelta(minutes=int(sup_open_delay_min))
    universe_at = close_at + datetime.timedelta(minutes=int(sup_uni_after_close_min))

    sched = {
        "trading_date": open_at.date().isoformat(),
        "created_at_utc": _iso_utc_now(),
        "open_utc": open_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mid_utc": mid_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "close_utc": close_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market_close_utc_hint": market_close_hhmm,  # for UI reference
        "holdings_after_open_min": int(sup_open_delay_min),
        "holdings_utc": holdings_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "universe_after_close_min": int(sup_uni_after_close_min),
        "universe_utc": universe_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return sched

def _guard_double_run(trading_date: str) -> bool:
    lk = _lock_path(trading_date)
    if lk.exists():
        _write_log(f"Lock exists: {lk.name}; already executed for {trading_date}.")
        _status_update("already_ran", f"Supervisor already ran for {trading_date}.", {"trading_date": trading_date})
        return False
    try:
        lk.write_text(_iso_utc_now() + "\n", encoding="utf-8")
        return True
    except Exception as e:
        _write_log(f"[lock] ERROR cannot create {lk}: {e}")
        _status_update("failed", f"Supervisor failed creating lock: {e}")
        return False

# --- Main (one-shot) ---

def main() -> int:
    # Accept but do not rely on --date (template passes %Y-%m-%d) – schedule uses UTC today.
    provided_date = None
    for arg in sys.argv[1:]:
        if arg.startswith("--date="):
            provided_date = arg.split("=", 1)[1].strip()

    _write_state("analyzing")
    _write_log("Starting daily one-shot supervisor")
    _status_update("launched", "Supervisor launched.")

    # Compute and persist schedule
    try:
        schedule = _compute_schedule()
        _write_schedule_json(schedule)
        _write_log(f"Schedule: {json.dumps(schedule, sort_keys=True)}")
        _status_update("scheduled", "Supervisor scheduled.", {"schedule": schedule})
    except Exception as e:
        _write_log(f"[schedule] ERROR {e}")
        _write_state("error")
        _status_update("failed", f"Supervisor failed while scheduling: {e}")
        return 1

    trading_date = provided_date or schedule["trading_date"]
    if not _guard_double_run(trading_date):
        _status_update("scheduled", "Supervisor already executed today; lock present.", {"trading_date": trading_date})
        return 0  # consider already-run as success (idempotent behavior)

    rc_nonzero = False
    _status_update("running", "Supervisor running.", {"trading_date": trading_date})





    # ---- OPEN ----
    try:
        open_at = datetime.datetime.fromisoformat(schedule["open_utc"].replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if now < open_at:
            _write_log(f"Sleeping until OPEN {schedule['open_utc']}")
            _sleep_until(open_at)

        if _phase_boundary_check():
            return 0

        _write_state("trading")
        rc_open = _run_worker(
            f"{shlex.quote(sys.executable)} -m tbot_bot.strategy.strategy_router --session=open",
            _phase_log_path("open"),
        )
        rc_nonzero |= (rc_open != 0)
    except Exception as e:
        _write_log(f"[open] ERROR {e}")
        _write_state("error")
        _status_update("failed", f"Supervisor failed during OPEN: {e}")
        return 1

    # ---- HOLDINGS (after open) ----
    try:
        hold_at = datetime.datetime.fromisoformat(schedule["holdings_utc"].replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if now < hold_at:
            _write_log(f"Sleeping until HOLDINGS {schedule['holdings_utc']}")
            _sleep_until(hold_at)

        if _phase_boundary_check():
            return 0

        _write_state("updating")
        rc_hold = _run_worker(
            f"{shlex.quote(sys.executable)} -m tbot_bot.runtime.holdings_maintenance",
            _phase_log_path("holdings"),
        )
        rc_nonzero |= (rc_hold != 0)
    except Exception as e:
        _write_log(f"[holdings] ERROR {e}")
        _write_state("error")
        _status_update("failed", f"Supervisor failed during HOLDINGS: {e}")
        return 1

    # ---- MID ----
    try:
        mid_at = datetime.datetime.fromisoformat(schedule["mid_utc"].replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if now < mid_at:
            _write_log(f"Sleeping until MID {schedule['mid_utc']}")
            _sleep_until(mid_at)

        if _phase_boundary_check():
            return 0

        _write_state("trading")
        rc_mid = _run_worker(
            f"{shlex.quote(sys.executable)} -m tbot_bot.strategy.strategy_router --session=mid",
            _phase_log_path("mid"),
        )
        rc_nonzero |= (rc_mid != 0)
    except Exception as e:
        _write_log(f"[mid] ERROR {e}")
        _write_state("error")
        _status_update("failed", f"Supervisor failed during MID: {e}")
        return 1

    # ---- CLOSE ----
    try:
        close_at = datetime.datetime.fromisoformat(schedule["close_utc"].replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if now < close_at:
            _write_log(f"Sleeping until CLOSE {schedule['close_utc']}")
            _sleep_until(close_at)

        if _phase_boundary_check():
            return 0

        _write_state("trading")
        rc_close = _run_worker(
            f"{shlex.quote(sys.executable)} -m tbot_bot.strategy.strategy_router --session=close",
            _phase_log_path("close"),
        )
        rc_nonzero |= (rc_close != 0)
    except Exception as e:
        _write_log(f"[close] ERROR {e}")
        _write_state("error")
        _status_update("failed", f"Supervisor failed during CLOSE: {e}")
        return 1

    # ---- UNIVERSE (after close) ----
    try:
        uni_at = datetime.datetime.fromisoformat(schedule["universe_utc"].replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if now < uni_at:
            _write_log(f"Sleeping until UNIVERSE {schedule['universe_utc']}")
            _sleep_until(uni_at)

        if _phase_boundary_check():
            return 0

        _write_state("updating")
        rc_universe = _run_worker(
            f"{shlex.quote(sys.executable)} -m tbot_bot.screeners.universe_orchestrator",
            _phase_log_path("universe"),
        )
        rc_nonzero |= (rc_universe != 0)
    except Exception as e:
        _write_log(f"[universe] ERROR {e}")
        _write_state("error")
        _status_update("failed", f"Supervisor failed during UNIVERSE: {e}")
        return 1

    _write_state("idle")
    _write_log(f"Supervisor complete. rc_nonzero={int(rc_nonzero)}")
    _status_update("complete", "Supervisor complete.", {"rc_nonzero": int(rc_nonzero)})
    return 0 if not rc_nonzero else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _write_log("Interrupted by user")
        try:
            _write_state("shutdown_triggered")
            _status_update("failed", "Supervisor interrupted by user (KeyboardInterrupt).")
        except Exception:
            pass
        sys.exit(130)
