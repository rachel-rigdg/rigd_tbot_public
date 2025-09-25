# tbot_bot/runtime/schedule_dispatcher.py
# Single source of truth for executing the daily schedule produced by tbot_supervisor.
# Follows times in logs/schedule.json with grace windows; honors control flags; updates bot_state; writes per-phase logs.

# --- PATH BOOTSTRAP ---
import sys as _sys, pathlib as _pathlib
_THIS = _pathlib.Path(__file__).resolve()
_ROOT = _THIS.parents[2]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
# --- END BOOTSTRAP ---

import os
import sys
import shlex
import json
import time
import datetime
import subprocess
from pathlib import Path
from typing import Dict, Optional

def _iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def _out_path(category: str, filename: str) -> Path:
    from tbot_bot.support.path_resolver import get_output_path
    p = Path(get_output_path(category=category, filename=filename))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

STATUS_PATH = _out_path("logs", "status.json")
SCHEDULE_PATH = _out_path("logs", "schedule.json")
LOG_PATH = _out_path("logs", "schedule_dispatcher.log")
CONTROL_DIR = _ROOT / "tbot_bot" / "control"
BOT_STATE = CONTROL_DIR / "bot_state.txt"
FLAG_STOP = CONTROL_DIR / "control_stop.flag"
FLAG_KILL = CONTROL_DIR / "control_kill.flag"

def _log(msg: str):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{_iso()} [dispatcher] {msg}\n")

def _write_state(state: str):
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    BOT_STATE.write_text(state.strip() + "\n", encoding="utf-8")

def _write_status(extra: Dict):
    payload = {}
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
    except Exception:
        payload = {}
    payload.update(extra or {})
    payload["dispatcher_updated_at"] = _iso()
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

def _phase_log(name: str) -> Path:
    return _out_path("logs", f"{name}.log")

def _read_schedule() -> Dict:
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _dt(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))

def _sleep_until(ts: datetime.datetime):
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        rem = (ts - now).total_seconds()
        if rem <= 0:
            return
        time.sleep(min(rem, 60))

def _grace_min() -> int:
    try:
        return int(os.environ.get("TBOT_SUP_PHASE_GRACE_MIN", "2"))
    except Exception:
        return 2

def _should_run_or_skip(target_dt: Optional[datetime.datetime], phase: str) -> bool:
    if not target_dt:
        _log(f"{phase}: no scheduled time → run now.")
        return True
    now = datetime.datetime.now(datetime.timezone.utc)
    if now < target_dt:
        _log(f"{phase}: sleeping until {target_dt.isoformat()}Z")
        _sleep_until(target_dt)
        return True
    late = (now - target_dt).total_seconds()
    grace = max(0, _grace_min()) * 60
    if late <= grace:
        _log(f"{phase}: late by {int(late)}s (≤ {grace//60}m grace) → running now.")
        return True
    _log(f"{phase}: missed by {int(late//60)}m {int(late%60)}s (> grace) → skipping.")
    return False

def _flag() -> Optional[str]:
    if FLAG_KILL.exists():
        return "kill"
    if FLAG_STOP.exists():
        return "stop"
    return None

def _boundary_check() -> Optional[str]:
    fl = _flag()
    if fl == "kill":
        _write_state("shutdown_triggered")
        _log("Kill flag detected. Aborting.")
        _write_status({"dispatcher_status": "aborted", "reason": "kill"})
        return "kill"
    if fl == "stop":
        _write_state("graceful_closing_positions")
        _log("Stop flag detected. Halting further phases.")
        _write_status({"dispatcher_status": "stopped", "reason": "stop"})
        return "stop"
    return None

def _py() -> str:
    return os.environ.get("TBOT_PY", sys.executable)

def _run(cmd: str, phase: str) -> int:
    env = os.environ.copy()
    # ensure repo on path
    repo = str(_ROOT)
    cur = env.get("PYTHONPATH", "")
    if repo not in cur.split(os.pathsep):
        env["PYTHONPATH"] = f"{repo}{os.pathsep}{cur}" if cur else repo

    logp = _phase_log(phase)
    with open(logp, "ab", buffering=0) as lf:
        try:
            _log(f"Exec[{phase}]: {cmd}")
            p = subprocess.Popen(shlex.split(cmd), cwd=str(_ROOT), stdout=lf, stderr=lf, env=env)
            rc = p.wait()
            _log(f"Exit[{phase}]: {rc}")
            return int(rc)
        except Exception as e:
            msg = f"[{phase}] spawn error: {e}"
            _log(msg)
            try:
                lf.write((msg + "\n").encode("utf-8", errors="ignore"))
            except Exception:
                pass
            return 1

def _lock_path(trading_date: str) -> Path:
    return _out_path("locks", f"dispatcher_{trading_date}.lock")

def main() -> int:
    try:
        sched = _read_schedule()
    except Exception as e:
        _log(f"ERROR reading schedule.json: {e}")
        _write_status({"dispatcher_status": "failed", "message": f"schedule read error: {e}"})
        _write_state("error")
        return 1

    td = sched.get("trading_date") or datetime.datetime.utcnow().date().isoformat()
    lk = _lock_path(td)
    if lk.exists():
        _log(f"Lock exists for {td}; another dispatcher likely ran. Exiting.")
        _write_status({"dispatcher_status": "already_ran", "trading_date": td})
        return 0
    try:
        lk.write_text(_iso() + "\n", encoding="utf-8")
    except Exception as e:
        _log(f"WARN cannot write dispatcher lock: {e}")

    rc_nonzero = False
    _write_status({"dispatcher_status": "running", "trading_date": td})

    # OPEN
    if _boundary_check(): return 0
    if _should_run_or_skip(_dt(sched["open_utc"]), "OPEN"):
        _write_state("trading")
        rc = _run(f"{shlex.quote(_py())} -m tbot_bot.strategy.strategy_router --session=open", "open")
        rc_nonzero |= (rc != 0)

    # HOLDINGS after open
    if _boundary_check(): return 0
    hold_open_str = sched.get("holdings_open_utc") or sched.get("holdings_utc")
    hold_open_dt = _dt(hold_open_str) if hold_open_str else None
    if _should_run_or_skip(hold_open_dt, "HOLDINGS(open)"):
        _write_state("updating")
        rc = _run(f"{shlex.quote(_py())} -m tbot_bot.runtime.holdings_maintenance --session=open", "holdings_open")
        rc_nonzero |= (rc != 0)

    # MID
    if _boundary_check(): return 0
    if _should_run_or_skip(_dt(sched["mid_utc"]), "MID"):
        _write_state("trading")
        rc = _run(f"{shlex.quote(_py())} -m tbot_bot.strategy.strategy_router --session=mid", "mid")
        rc_nonzero |= (rc != 0)

    # HOLDINGS after mid
    if _boundary_check(): return 0
    hold_mid_str = sched.get("holdings_mid_utc")
    hold_mid_dt = _dt(hold_mid_str) if hold_mid_str else None
    if _should_run_or_skip(hold_mid_dt, "HOLDINGS(mid)"):
        _write_state("updating")
        rc = _run(f"{shlex.quote(_py())} -m tbot_bot.runtime.holdings_maintenance --session=mid", "holdings_mid")
        rc_nonzero |= (rc != 0)

    # CLOSE
    if _boundary_check(): return 0
    if _should_run_or_skip(_dt(sched["close_utc"]), "CLOSE"):
        _write_state("trading")
        rc = _run(f"{shlex.quote(_py())} -m tbot_bot.strategy.strategy_router --session=close", "close")
        rc_nonzero |= (rc != 0)

    # UNIVERSE after close
    if _boundary_check(): return 0
    uni_dt = _dt(sched["universe_utc"]) if sched.get("universe_utc") else None
    if _should_run_or_skip(uni_dt, "UNIVERSE"):
        _write_state("updating")
        rc = _run(f"{shlex.quote(_py())} -m tbot_bot.screeners.universe_orchestrator", "universe")
        rc_nonzero |= (rc != 0)

    _write_state("idle")
    _write_status({"dispatcher_status": "complete", "rc_nonzero": int(rc_nonzero)})
    _log(f"Dispatcher complete. rc_nonzero={int(rc_nonzero)}")
    return 0 if not rc_nonzero else 1

if __name__ == "__main__":
    sys.exit(main())
