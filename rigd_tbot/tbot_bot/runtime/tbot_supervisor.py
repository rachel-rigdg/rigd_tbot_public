# tbot_bot/runtime/tbot_supervisor.py
# Central phase/process supervisor for TradeBot.

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone, time as dt_time
from typing import Optional

from tbot_bot.support.utils_time import utc_now

# --- Read schedule strictly via env_bot getters (UTC) ---
from tbot_bot.config.env_bot import (
    get_open_time_utc,
    get_mid_time_utc,
    get_close_time_utc,
    get_market_close_utc,
)

# --- Router import (call directly instead of launching strategy scripts) ---
from tbot_bot.strategy.strategy_router import route_strategy

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"
CONTROL_START_FLAG = CONTROL_DIR / "control_start.flag"
CONTROL_STOP_FLAG = CONTROL_DIR / "control_stop.flag"
CONTROL_KILL_FLAG = CONTROL_DIR / "control_kill.flag"  # honor .flag suffix

# Per-day guard stamps (ISO-8601 UTC instants)
LAST_OPEN_STAMP  = CONTROL_DIR / "last_strategy_open_utc.txt"
LAST_MID_STAMP   = CONTROL_DIR / "last_strategy_mid_utc.txt"
LAST_CLOSE_STAMP = CONTROL_DIR / "last_strategy_close_utc.txt"

# Launch registry (single source of truth for module names)
from tbot_bot.support.launch_registry import (
    spawn_module,            # to launch a worker
    is_process_running,      # singleton check
    NON_RESTARTABLE,         # one-offs policy (do NOT shadow locally)
)

UNIVERSE_TIMESTAMP_PATH = ROOT_DIR / "tbot_bot" / "output" / "screeners" / "symbol_universe.json"
REBUILD_DELAY_HOURS = 4

BOOT_PHASES = ("initialize", "provisioning", "bootstrapping", "registration")

def read_env_var(key, default=None):
    from tbot_bot.config.env_bot import load_env_bot_config
    env = load_env_bot_config()
    return env.get(key, default)

# Configurable strategy launch window (default 300s)
STRATEGY_WINDOW_SEC = int(read_env_var("STRATEGY_WINDOW_SEC", "300"))

# Throttle universe attempts before creds exist (avoid rapid relaunch loops)
UNIVERSE_LAST_ATTEMPT_PATH = CONTROL_DIR / "last_universe_attempt_utc.txt"
UNIVERSE_RETRY_COOLDOWN_MIN = int(read_env_var("UNIVERSE_RETRY_COOLDOWN_MIN", "30"))

def read_bot_state():
    try:
        return BOT_STATE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""

def _spawn_for(name: str, **popen_kwargs):
    print(f"[tbot_supervisor] launching process: {name}", flush=True)
    return spawn_module(name, **popen_kwargs)

def ensure_singleton(name_or_hint: str) -> bool:
    return is_process_running(name_or_hint)

def find_individual_test_flags():
    return list(CONTROL_DIR.glob("test_mode_*.flag"))

def _to_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce to aware UTC using datetime.timezone.utc; pass None through."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _read_stamp(path: Path):
    if not path.exists():
        return None
    try:
        txt = path.read_text(encoding="utf-8").strip()
        if txt.endswith("Z"):
            txt = txt.replace("Z", "+00:00")
        return datetime.fromisoformat(txt)
    except Exception:
        return None

def _write_stamp(path: Path, when: datetime):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        aware = _to_aware_utc(when) or datetime.now(timezone.utc)
        path.write_text(aware.isoformat().replace("+00:00", "Z"), encoding="utf-8")
    except Exception as e:
        print(f"[tbot_supervisor] WARN failed to write stamp {path.name}: {e}", flush=True)

def _has_run_today(stamp_path: Path, now_utc: datetime) -> bool:
    ts = _read_stamp(stamp_path)
    ts = _to_aware_utc(ts)
    return bool(ts and ts.date() == now_utc.date())

def is_time_for_universe_rebuild():
    # Determine last build time
    if not UNIVERSE_TIMESTAMP_PATH.exists():
        build_time = None
    else:
        try:
            import json
            with open(UNIVERSE_TIMESTAMP_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            build_time_str = data.get("build_timestamp_utc")
            if build_time_str:
                if build_time_str.endswith("Z"):
                    build_time_str = build_time_str.replace("Z", "+00:00")
                build_time = datetime.fromisoformat(build_time_str)
            else:
                build_time = datetime.utcfromtimestamp(UNIVERSE_TIMESTAMP_PATH.stat().st_mtime)
        except Exception:
            build_time = datetime.utcfromtimestamp(UNIVERSE_TIMESTAMP_PATH.stat().st_mtime)

    now = _to_aware_utc(utc_now())
    build_time = _to_aware_utc(build_time)

    market_close_str = get_market_close_utc() or "21:00"  # getter (UTC HH:MM)
    close_time = _parse_time_hhmm(market_close_str)
    today_close = now.replace(hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0)

    last_close = today_close - timedelta(days=1) if now < today_close else today_close
    scheduled_time = last_close + timedelta(hours=REBUILD_DELAY_HOURS)

    # If we've never built, throttle attempts by cooldown window
    if build_time is None:
        last_attempt = _to_aware_utc(_read_stamp(UNIVERSE_LAST_ATTEMPT_PATH))
        if last_attempt and (now - last_attempt) < timedelta(minutes=UNIVERSE_RETRY_COOLDOWN_MIN):
            return False
        return now >= scheduled_time

    # All aware UTC now — safe to compare
    return now >= scheduled_time and build_time < scheduled_time

# --- BROKER SYNC NIGHTLY LAUNCH LOGIC ---
def get_last_sync_broker_ledger_timestamp():
    ts_path = CONTROL_DIR / "last_broker_sync_utc.txt"
    if not ts_path.exists():
        return None
    try:
        txt = ts_path.read_text().strip()
        if txt.endswith("Z"):
            txt = txt.replace("Z", "+00:00")
        return datetime.fromisoformat(txt)
    except Exception:
        return None

def set_last_sync_broker_ledger_timestamp(dt: datetime):
    ts_path = CONTROL_DIR / "last_broker_sync_utc.txt"
    aware = _to_aware_utc(dt) or datetime.now(timezone.utc)
    ts_path.write_text(aware.isoformat().replace("+00:00", "Z"))

def is_time_for_broker_sync():
    now = _to_aware_utc(utc_now())
    market_close_str = get_market_close_utc() or "21:00"
    sync_delay_min = int(read_env_var("BROKER_SYNC_DELAY_MIN", "30"))
    close_time = _parse_time_hhmm(market_close_str)
    today_close = now.replace(hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0)
    if now < today_close:
        sync_time = today_close - timedelta(days=1) + timedelta(minutes=sync_delay_min)
    else:
        sync_time = today_close + timedelta(minutes=sync_delay_min)
    last_sync = _to_aware_utc(get_last_sync_broker_ledger_timestamp())
    already_synced_today = last_sync and last_sync.date() == now.date() and last_sync > sync_time - timedelta(minutes=5)
    return now >= sync_time and not already_synced_today

# --- LEDGER SNAPSHOT NIGHTLY LAUNCH LOGIC ---
def get_last_ledger_snapshot_timestamp():
    ts_path = CONTROL_DIR / "last_ledger_snapshot_utc.txt"
    if not ts_path.exists():
        return None
    try:
        txt = ts_path.read_text().strip()
        if txt.endswith("Z"):
            txt = txt.replace("Z", "+00:00")
        return datetime.fromisoformat(txt)
    except Exception:
        return None

def set_last_ledger_snapshot_timestamp(dt: datetime):
    ts_path = CONTROL_DIR / "last_ledger_snapshot_utc.txt"
    aware = _to_aware_utc(dt) or datetime.now(timezone.utc)
    ts_path.write_text(aware.isoformat().replace("+00:00", "Z"))

def is_time_for_ledger_snapshot():
    # Uses the same window as broker sync (30min after close)
    now = _to_aware_utc(utc_now())
    market_close_str = get_market_close_utc() or "21:00"
    snapshot_delay_min = int(read_env_var("LEDGER_SNAPSHOT_DELAY_MIN", "30"))
    close_time = _parse_time_hhmm(market_close_str)
    today_close = now.replace(hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0)
    if now < today_close:
        snap_time = today_close - timedelta(days=1) + timedelta(minutes=snapshot_delay_min)
    else:
        snap_time = today_close + timedelta(minutes=snapshot_delay_min)
    last_snapshot = _to_aware_utc(get_last_ledger_snapshot_timestamp())
    already_snapshotted_today = last_snapshot and last_snapshot.date() == now.date() and last_snapshot > snap_time - timedelta(minutes=5)
    return now >= snap_time and not already_snapshotted_today

def _parse_time_hhmm(hhmm_utc: str) -> dt_time:
    """Parse 'HH:MM' to a time object (UTC semantics)."""
    try:
        hh, mm = map(int, hhmm_utc.strip().split(":"))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return dt_time(hour=hh, minute=mm)
    except Exception:
        pass
    # Fallback to 00:00 on invalid input
    return dt_time(0, 0)

def _scheduled_run_datetime(hhmm_utc: str, now: datetime) -> datetime:
    t = _parse_time_hhmm(hhmm_utc)
    return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)

def _run_via_router(which: str) -> bool:
    """
    Call the router with override and print a concise result line.
    Returns True only if the router actually ran (not skipped and no exception).
    """
    print(f"[tbot_supervisor] Launching via router: {which}", flush=True)
    try:
        res = route_strategy(override=which)
        if getattr(res, "skipped", False):
            print(f"[tbot_supervisor] Router {which}: skipped (errors={len(getattr(res, 'errors', []) or [])})", flush=True)
            return False
        trades = getattr(res, "trades", []) or []
        print(f"[tbot_supervisor] Router {which}: completed (trades={len(trades)}, errors={len(getattr(res, 'errors', []) or [])})", flush=True)
        return True
    except Exception as e:
        print(f"[tbot_supervisor] Router {which}: exception: {e}", flush=True)
        return False

def launch_strategy_if_time(strategy_name, processes, state):
    """Launch strategy within ±window via router; per-day guard; state == 'running' required."""
    if state != "running":
        return

    now = _to_aware_utc(utc_now())
    if strategy_name == "open":
        hhmm = get_open_time_utc() or "13:30"
        stamp = LAST_OPEN_STAMP
    elif strategy_name == "mid":
        hhmm = get_mid_time_utc() or "16:00"
        stamp = LAST_MID_STAMP
    elif strategy_name == "close":
        hhmm = get_close_time_utc() or "19:45"
        stamp = LAST_CLOSE_STAMP
    else:
        return

    # Per-day guard
    if _has_run_today(stamp, now):
        return

    run_time = _scheduled_run_datetime(hhmm, now)
    delta = (now - run_time).total_seconds()

    if abs(delta) <= STRATEGY_WINDOW_SEC:
        # Only stamp if the router actually ran
        ran = _run_via_router(strategy_name)
        if ran:
            _write_stamp(stamp, now)
        else:
            print(f"[tbot_supervisor] Router '{strategy_name}' did not run; stamp not written.", flush=True)

def _late_open_catchup():
    """
    One-time catch-up for OPEN if we just transitioned to running and missed the window by ≤300s.
    Only stamps if router actually runs.
    """
    now = _to_aware_utc(utc_now())
    hhmm = get_open_time_utc() or "13:30"
    run_time = _scheduled_run_datetime(hhmm, now)
    if 0 < (now - run_time).total_seconds() <= 300 and not _has_run_today(LAST_OPEN_STAMP, now):
        print(f"[tbot_supervisor] Late launch candidate: OPEN (scheduled {hhmm}Z, now {now.strftime('%H:%M:%SZ')})", flush=True)
        ran = _run_via_router("open")
        if ran:
            _write_stamp(LAST_OPEN_STAMP, now)
            print(f"[tbot_supervisor] Late launch: OPEN stamped @ {now.isoformat()}", flush=True)
        else:
            print("[tbot_supervisor] Late launch OPEN skipped/failed; stamp not written.", flush=True)

def main():
    print("[tbot_supervisor] Starting TradeBot phase supervisor.", flush=True)
    processes = {}

    launch_targets = [
        "status_bot",
        "watchdog_bot",
        # DO NOT LAUNCH strategy_router here — it is not a worker.
        "risk_module",
        "kill_switch",
        "log_rotation",
        "trade_logger",
        "status_logger",
    ]

    persistent_ops = [
        "holdings_manager"
    ]

    previous_state = None
    if BOT_STATE_PATH.exists():
        previous_state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        if previous_state not in ("idle", "running", "started", "trading", "monitoring", "analyzing", "updating", "stopped"):
            previous_state = "idle"

    # Kill stale status_bot (best-effort)
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
                if "-m tbot_bot.runtime.status_bot" in cmd or "status_bot.py" in cmd:
                    print(f"[tbot_supervisor] Killing stale status_bot.py process PID {proc.info['pid']}", flush=True)
                    proc.kill()
            except Exception:
                continue
    except Exception:
        pass

    # Launch status_bot (live status process)
    status_bot_proc = _spawn_for("status_bot")
    print("[tbot_supervisor] Launched status_bot.py as dedicated live status process.", flush=True)

    for name in launch_targets:
        if name == "status_bot":
            continue
        if not ensure_singleton(name):
            print(f"[tbot_supervisor] Launching {name}...", flush=True)
            processes[name] = _spawn_for(name)
        else:
            print(f"[tbot_supervisor] {name} already running.", flush=True)

    first_loop = True

    try:
        while True:
            state = read_bot_state()

            if CONTROL_KILL_FLAG.exists():
                BOT_STATE_PATH.write_text("shutdown", encoding="utf-8")
                print("[tbot_supervisor] CONTROL_KILL_FLAG detected. Set bot state to 'shutdown'.", flush=True)
                CONTROL_KILL_FLAG.unlink(missing_ok=True)

            if state in ("shutdown", "shutdown_triggered", "error"):
                print(f"[tbot_supervisor] Detected shutdown/error state: {state}. Terminating subprocesses and exiting.", flush=True)
                break

            # Only after provisioning/bootstrapping complete
            if state not in BOOT_PHASES:
                # Gate holdings_manager on {'idle','running'}
                if state in {"idle", "running"}:
                    for name in persistent_ops:
                        if not ensure_singleton(name):
                            print(f"[tbot_supervisor] Launching {name} as persistent worker...", flush=True)
                            processes[name] = _spawn_for(name)
                        else:
                            print(f"[tbot_supervisor] {name} already running.", flush=True)

                # Scheduled strategy launches (only when state == 'running'), via router
                launch_strategy_if_time("open", processes, state)
                launch_strategy_if_time("mid", processes, state)
                launch_strategy_if_time("close", processes, state)

                # One-time late catch-up for OPEN on transition to 'running'
                # Also handle the case where we *start up already in 'running'*
                if ((previous_state != "running") or first_loop) and state == "running":
                    _late_open_catchup()

                # ---- BROKER SYNC NIGHTLY (once per day) ----
                if is_time_for_broker_sync():
                    if not ensure_singleton("sync_broker_ledger"):
                        print("[tbot_supervisor] Launching nightly broker sync (sync_broker_ledger)...", flush=True)
                        _spawn_for("sync_broker_ledger")
                        set_last_sync_broker_ledger_timestamp(utc_now())
                    else:
                        print("[tbot_supervisor] Broker sync already running.", flush=True)

                # ---- LEDGER SNAPSHOT NIGHTLY (once per day) ----
                if is_time_for_ledger_snapshot():
                    if not ensure_singleton("ledger_snapshot"):
                        print("[tbot_supervisor] Launching nightly EOD ledger snapshot (ledger_snapshot)...", flush=True)
                        _spawn_for("ledger_snapshot")
                        set_last_ledger_snapshot_timestamp(utc_now())
                    else:
                        print("[tbot_supervisor] Ledger snapshot already running.", flush=True)

            if TEST_MODE_FLAG.exists():
                print("[tbot_supervisor] Global TEST_MODE flag detected. Launching integration_test_runner...", flush=True)
                if not ensure_singleton("integration_test_runner"):
                    processes["integration_test_runner"] = _spawn_for("integration_test_runner")
                while TEST_MODE_FLAG.exists():
                    time.sleep(1)
                print("[tbot_supervisor] Global TEST_MODE complete. Test runner finished.", flush=True)

            individual_flags = find_individual_test_flags()
            if individual_flags:
                for flag_path in individual_flags:
                    test_name = flag_path.stem.replace("test_mode_", "")
                    print(f"[tbot_supervisor] Detected individual TEST_MODE flag for '{test_name}'. Launching corresponding test module...", flush=True)
                    module_name = f"tbot_bot.test.test_{test_name}"
                    short = f"test_{test_name}"
                    if not ensure_singleton(short):
                        processes[f"test_runner_{test_name}"] = subprocess.Popen(
                            ["python3", "-u", "-m", module_name], stdout=None, stderr=None
                        )
                    while flag_path.exists():
                        time.sleep(1)
                    print(f"[tbot_supervisor] Individual TEST_MODE '{test_name}' complete.", flush=True)

            if CONTROL_START_FLAG.exists():
                BOT_STATE_PATH.write_text("running", encoding="utf-8")
                print("[tbot_supervisor] CONTROL_START_FLAG detected. Set bot state to 'running'.", flush=True)
                CONTROL_START_FLAG.unlink(missing_ok=True)

            if CONTROL_STOP_FLAG.exists():
                BOT_STATE_PATH.write_text("idle", encoding="utf-8")
                print("[tbot_supervisor] CONTROL_STOP_FLAG detected. Set bot state to 'idle'.", flush=True)
                CONTROL_STOP_FLAG.unlink(missing_ok=True)

            if is_time_for_universe_rebuild():
                # Treat universe build as one-off
                if not ensure_singleton("universe_orchestrator"):
                    print("[tbot_supervisor] Triggering universe cache rebuild (universe_orchestrator)...", flush=True)
                    # record attempt to avoid tight loops before creds are added
                    _write_stamp(UNIVERSE_LAST_ATTEMPT_PATH, utc_now())
                    processes["universe_orchestrator"] = _spawn_for("universe_orchestrator")
                else:
                    print("[tbot_supervisor] Universe cache rebuild already running.", flush=True)

            # Restart policy (exclude one-offs; remove finished from tracking)
            to_remove = []
            for name, proc in list(processes.items()):
                if proc.poll() is not None:
                    if name in NON_RESTARTABLE:
                        print(f"[tbot_supervisor] {name} finished (one-off). Not restarting.", flush=True)
                        to_remove.append(name)
                    else:
                        print(f"[tbot_supervisor] {name} has died. Restarting...", flush=True)
                        processes[name] = _spawn_for(name)
            for name in to_remove:
                processes.pop(name, None)

            previous_state = state
            first_loop = False
            time.sleep(2)

    except KeyboardInterrupt:
        print("[tbot_supervisor] KeyboardInterrupt received, terminating.", flush=True)

    finally:
        for pname, proc in processes.items():
            try:
                print(f"[tbot_supervisor] Terminating {pname} process...", flush=True)
                proc.terminate()
            except Exception as e:
                print(f"[tbot_supervisor] Exception terminating {pname}: {e}", flush=True)
        if 'status_bot_proc' in locals() and status_bot_proc:
            try:
                print("[tbot_supervisor] Terminating status_bot.py process...", flush=True)
                status_bot_proc.terminate()
            except Exception as e:
                print(f"[tbot_supervisor] Exception terminating status_bot.py: {e}", flush=True)

if __name__ == "__main__":
    main()
