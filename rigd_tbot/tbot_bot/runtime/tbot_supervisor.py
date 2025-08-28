# tbot_bot/runtime/tbot_supervisor.py
# Central phase/process supervisor for TradeBot.
# Responsible for all phase transitions, persistent monitoring, and launching all watcher/worker/test runner processes.
# Only launched by main.py after successful provisioning/bootstrapping and transition to operational state.
# No watcher/worker/test runner is ever launched except by this supervisor.

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

from tbot_bot.support import path_resolver
from tbot_bot.support.utils_time import utc_now, parse_time_utc

# --- NEW: read schedule strictly via env_bot getters (UTC) ---
from tbot_bot.config.env_bot import (
    get_open_time_utc,
    get_mid_time_utc,
    get_close_time_utc,
    get_market_close_utc,
)

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

STATUS_BOT_PATH = path_resolver.resolve_runtime_script_path("status_bot.py")
WATCHDOG_BOT_PATH = path_resolver.resolve_runtime_script_path("watchdog_bot.py")
STRATEGY_ROUTER_PATH = path_resolver.resolve_runtime_script_path("strategy_router.py")
STRATEGY_OPEN_PATH = path_resolver.resolve_runtime_script_path("strategy_open.py")
STRATEGY_MID_PATH = path_resolver.resolve_runtime_script_path("strategy_mid.py")
STRATEGY_CLOSE_PATH = path_resolver.resolve_runtime_script_path("strategy_close.py")
RISK_MODULE_PATH = path_resolver.resolve_runtime_script_path("risk_module.py")
KILL_SWITCH_PATH = path_resolver.resolve_runtime_script_path("kill_switch.py")
LOG_ROTATION_PATH = path_resolver.resolve_runtime_script_path("log_rotation.py")
TRADE_LOGGER_PATH = path_resolver.resolve_runtime_script_path("trade_logger.py")
STATUS_LOGGER_PATH = path_resolver.resolve_runtime_script_path("status_logger.py")
UNIVERSE_ORCHESTRATOR_PATH = path_resolver.resolve_runtime_script_path("universe_orchestrator.py")
INTEGRATION_TEST_RUNNER_PATH = path_resolver.resolve_runtime_script_path("integration_test_runner.py")
HOLDINGS_MANAGER_PATH = path_resolver.resolve_runtime_script_path("holdings_manager.py")
SYNC_BROKER_LEDGER_PATH = path_resolver.resolve_runtime_script_path("sync_broker_ledger.py")
LEDGER_SNAPSHOT_PATH = path_resolver.resolve_runtime_script_path("ledger_snapshot.py")

UNIVERSE_TIMESTAMP_PATH = ROOT_DIR / "tbot_bot" / "output" / "screeners" / "symbol_universe.json"
REBUILD_DELAY_HOURS = 4

BOOT_PHASES = ("initialize", "provisioning", "bootstrapping", "registration")

# One-off processes that must NOT be auto-restarted
NON_RESTARTABLE = {"strategy_open", "strategy_mid", "strategy_close", "universe_orchestrator"}

def read_env_var(key, default=None):
    from tbot_bot.config.env_bot import load_env_bot_config
    env = load_env_bot_config()
    return env.get(key, default)

def read_bot_state():
    try:
        return BOT_STATE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""

def launch_subprocess(cmd_path):
    return subprocess.Popen(["python3", str(cmd_path)], stdout=None, stderr=None)

def ensure_singleton(process_name):
    import psutil
    for proc in psutil.process_iter(["cmdline"]):
        try:
            if process_name in " ".join(proc.info["cmdline"]):
                return True
        except Exception:
            continue
    return False

def find_individual_test_flags():
    return list(CONTROL_DIR.glob("test_mode_*.flag"))

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
        path.write_text(when.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"), encoding="utf-8")
    except Exception as e:
        print(f"[tbot_supervisor] WARN failed to write stamp {path.name}: {e}")

def _has_run_today(stamp_path: Path, now_utc: datetime) -> bool:
    ts = _read_stamp(stamp_path)
    return bool(ts and ts.date() == now_utc.date())

def is_time_for_universe_rebuild():
    if not UNIVERSE_TIMESTAMP_PATH.exists():
        return True
    try:
        import json
        data = json.load(open(UNIVERSE_TIMESTAMP_PATH, "r"))
        build_time_str = data.get("build_timestamp_utc")
        if build_time_str:
            if build_time_str.endswith("Z"):
                build_time_str = build_time_str.replace("Z", "+00:00")
            build_time = datetime.fromisoformat(build_time_str)
        else:
            build_time = datetime.utcfromtimestamp(UNIVERSE_TIMESTAMP_PATH.stat().st_mtime)
    except Exception:
        build_time = datetime.utcfromtimestamp(UNIVERSE_TIMESTAMP_PATH.stat().st_mtime)
    now = utc_now()
    market_close_str = get_market_close_utc() or "21:00"  # getter (UTC HH:MM)
    close_time = parse_time_utc(market_close_str)
    today_close = now.replace(hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0)
    if now < today_close:
        last_close = today_close - timedelta(days=1)
    else:
        last_close = today_close
    scheduled_time = last_close + timedelta(hours=REBUILD_DELAY_HOURS)
    return now >= scheduled_time and build_time < scheduled_time

# --- BROKER SYNC NIGHTLY LAUNCH LOGIC (timezone-safe; market close via getter) ---
def get_last_sync_broker_ledger_timestamp():
    ts_path = CONTROL_DIR / "last_broker_sync_utc.txt"
    if not ts_path.exists():
        return None
    try:
        return datetime.fromisoformat(ts_path.read_text().strip())
    except Exception:
        return None

def set_last_sync_broker_ledger_timestamp(dt: datetime):
    ts_path = CONTROL_DIR / "last_broker_sync_utc.txt"
    ts_path.write_text(dt.isoformat())

def is_time_for_broker_sync():
    now = utc_now()
    market_close_str = get_market_close_utc() or "21:00"
    sync_delay_min = int(read_env_var("BROKER_SYNC_DELAY_MIN", "30"))
    close_time = parse_time_utc(market_close_str)
    today_close = now.replace(hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0)
    if now < today_close:
        sync_time = today_close - timedelta(days=1) + timedelta(minutes=sync_delay_min)
    else:
        sync_time = today_close + timedelta(minutes=sync_delay_min)
    last_sync = get_last_sync_broker_ledger_timestamp()
    already_synced_today = last_sync and last_sync.date() == now.date() and last_sync > sync_time - timedelta(minutes=5)
    return now >= sync_time and not already_synced_today

# --- LEDGER SNAPSHOT NIGHTLY LAUNCH LOGIC (identical schedule to broker sync) ---
def get_last_ledger_snapshot_timestamp():
    ts_path = CONTROL_DIR / "last_ledger_snapshot_utc.txt"
    if not ts_path.exists():
        return None
    try:
        return datetime.fromisoformat(ts_path.read_text().strip())
    except Exception:
        return None

def set_last_ledger_snapshot_timestamp(dt: datetime):
    ts_path = CONTROL_DIR / "last_ledger_snapshot_utc.txt"
    ts_path.write_text(dt.isoformat())

def is_time_for_ledger_snapshot():
    # Uses the same window as broker sync (30min after close)
    now = utc_now()
    market_close_str = get_market_close_utc() or "21:00"
    snapshot_delay_min = int(read_env_var("LEDGER_SNAPSHOT_DELAY_MIN", "30"))
    close_time = parse_time_utc(market_close_str)
    today_close = now.replace(hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0)
    if now < today_close:
        snap_time = today_close - timedelta(days=1) + timedelta(minutes=snapshot_delay_min)
    else:
        snap_time = today_close + timedelta(minutes=snapshot_delay_min)
    last_snapshot = get_last_ledger_snapshot_timestamp()
    already_snapshotted_today = last_snapshot and last_snapshot.date() == now.date() and last_snapshot > snap_time - timedelta(minutes=5)
    return now >= snap_time and not already_snapshotted_today

def _scheduled_run_datetime(hhmm_utc: str, now: datetime) -> datetime:
    t = parse_time_utc(hhmm_utc)
    run_dt = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    return run_dt

def launch_strategy_if_time(strategy_name, strategy_path, processes, state):
    """Launch strategy within ±300s window; per-day guard; state == 'running' required."""
    if state != "running":
        return

    now = utc_now()
    if strategy_name == "strategy_open":
        hhmm = get_open_time_utc() or "13:30"
        stamp = LAST_OPEN_STAMP
    elif strategy_name == "strategy_mid":
        hhmm = get_mid_time_utc() or "16:00"
        stamp = LAST_MID_STAMP
    elif strategy_name == "strategy_close":
        hhmm = get_close_time_utc() or "19:45"
        stamp = LAST_CLOSE_STAMP
    else:
        return

    # Per-day guard
    if _has_run_today(stamp, now):
        return

    run_time = _scheduled_run_datetime(hhmm, now)
    window_sec = 300  # widened from ±60s to ±300s
    delta = (now - run_time).total_seconds()
    if abs(delta) <= window_sec:
        script_name = os.path.basename(str(strategy_path))
        if not ensure_singleton(script_name):
            print(f"[tbot_supervisor] Launching {strategy_name} at scheduled time {hhmm}Z...")
            processes[strategy_name] = launch_subprocess(strategy_path)
            _write_stamp(stamp, now)  # mark launched to prevent duplicates
        else:
            print(f"[tbot_supervisor] {strategy_name} already running.")

def _late_open_catchup(processes):
    """One-time catch-up for OPEN if we just transitioned to running and missed the window by ≤300s."""
    now = utc_now()
    hhmm = get_open_time_utc() or "13:30"
    run_time = _scheduled_run_datetime(hhmm, now)
    # Only if scheduled time has passed, but not too far (≤300s), and not yet run today
    if 0 < (now - run_time).total_seconds() <= 300 and not _has_run_today(LAST_OPEN_STAMP, now):
        script_name = os.path.basename(str(STRATEGY_OPEN_PATH))
        if not ensure_singleton(script_name):
            print(f"[tbot_supervisor] Late launch: strategy_open (scheduled {hhmm}Z, actual {now.strftime('%H:%M:%SZ')})")
            processes["strategy_open"] = launch_subprocess(STRATEGY_OPEN_PATH)
            _write_stamp(LAST_OPEN_STAMP, now)

def main():
    print("[tbot_supervisor] Starting TradeBot phase supervisor.")
    processes = {}

    launch_targets = [
        ("status_bot", STATUS_BOT_PATH),
        ("watchdog_bot", WATCHDOG_BOT_PATH),
        ("strategy_router", STRATEGY_ROUTER_PATH),
        ("risk_module", RISK_MODULE_PATH),
        ("kill_switch", KILL_SWITCH_PATH),
        ("log_rotation", LOG_ROTATION_PATH),
        ("trade_logger", TRADE_LOGGER_PATH),
        ("status_logger", STATUS_LOGGER_PATH),
    ]

    persistent_ops = [
        ("holdings_manager", HOLDINGS_MANAGER_PATH)
    ]

    strategy_launchers = [
        ("strategy_open", STRATEGY_OPEN_PATH),
        ("strategy_mid", STRATEGY_MID_PATH),
        ("strategy_close", STRATEGY_CLOSE_PATH),
    ]

    previous_state = None
    is_first_bootstrap = False
    if BOT_STATE_PATH.exists():
        previous_state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        if previous_state not in (
            "idle", "running", "started", "trading", "monitoring", "analyzing", "updating", "stopped"
        ):
            previous_state = "idle"
    else:
        is_first_bootstrap = True

    # Force kill any stale status_bot.py before launching
    import psutil
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if "status_bot.py" in " ".join(proc.info["cmdline"]):
                print(f"[tbot_supervisor] Killing stale status_bot.py process PID {proc.info['pid']}")
                proc.kill()
        except Exception:
            continue

    # Launch status_bot.py as a persistent subprocess (always runs, updates status.json every 2s)
    status_bot_proc = launch_subprocess(STATUS_BOT_PATH)
    print("[tbot_supervisor] Launched status_bot.py as dedicated live status process.")

    for name, path in launch_targets:
        if name == "status_bot":
            continue
        script_name = os.path.basename(str(path))
        if not ensure_singleton(script_name):
            print(f"[tbot_supervisor] Launching {script_name}...")
            processes[name] = launch_subprocess(path)
        else:
            print(f"[tbot_supervisor] {script_name} already running.")

    try:
        while True:
            state = read_bot_state()

            if CONTROL_KILL_FLAG.exists():
                BOT_STATE_PATH.write_text("shutdown", encoding="utf-8")
                print("[tbot_supervisor] CONTROL_KILL_FLAG detected. Set bot state to 'shutdown'.")
                CONTROL_KILL_FLAG.unlink(missing_ok=True)

            if state in ("shutdown", "shutdown_triggered", "error"):
                print(f"[tbot_supervisor] Detected shutdown/error state: {state}. Terminating subprocesses and exiting.")
                break

            # Only after provisioning/bootstrapping complete
            if state not in BOOT_PHASES:
                # Gate holdings_manager on {'idle','running'}
                if state in {"idle", "running"}:
                    for name, path in persistent_ops:
                        if not ensure_singleton(os.path.basename(str(path))):
                            print(f"[tbot_supervisor] Launching {name} as persistent worker...")
                            processes[name] = launch_subprocess(path)
                        else:
                            print(f"[tbot_supervisor] {name} already running.")
                # Scheduled strategy launches (only when state == 'running')
                for strat_name, strat_path in strategy_launchers:
                    launch_strategy_if_time(strat_name, strat_path, processes, state)

                # One-time late catch-up for OPEN on transition to 'running'
                if previous_state != "running" and state == "running":
                    _late_open_catchup(processes)

                # ---- BROKER SYNC NIGHTLY (once per day) ----
                if is_time_for_broker_sync():
                    if not ensure_singleton("sync_broker_ledger.py"):
                        print("[tbot_supervisor] Launching nightly broker sync (sync_broker_ledger.py)...")
                        launch_subprocess(SYNC_BROKER_LEDGER_PATH)
                        set_last_sync_broker_ledger_timestamp(utc_now())
                    else:
                        print("[tbot_supervisor] Broker sync already running.")

                # ---- LEDGER SNAPSHOT NIGHTLY (once per day) ----
                if is_time_for_ledger_snapshot():
                    if not ensure_singleton("ledger_snapshot.py"):
                        print("[tbot_supervisor] Launching nightly EOD ledger snapshot (ledger_snapshot.py)...")
                        launch_subprocess(LEDGER_SNAPSHOT_PATH)
                        set_last_ledger_snapshot_timestamp(utc_now())
                    else:
                        print("[tbot_supervisor] Ledger snapshot already running.")

            if TEST_MODE_FLAG.exists():
                print("[tbot_supervisor] Global TEST_MODE flag detected. Launching integration_test_runner.py...")
                if not ensure_singleton("integration_test_runner.py"):
                    processes["test_runner"] = launch_subprocess(INTEGRATION_TEST_RUNNER_PATH)
                while TEST_MODE_FLAG.exists():
                    time.sleep(1)
                print("[tbot_supervisor] Global TEST_MODE complete. Test runner finished.")

            individual_flags = find_individual_test_flags()
            if individual_flags:
                for flag_path in individual_flags:
                    test_name = flag_path.stem.replace("test_mode_", "")
                    print(f"[tbot_supervisor] Detected individual TEST_MODE flag for '{test_name}'. Launching corresponding test module...")
                    module_name = f"tbot_bot.test.test_{test_name}"
                    if not ensure_singleton(module_name.split('.')[-1] + ".py"):
                        processes[f"test_runner_{test_name}"] = subprocess.Popen(
                            ["python3", "-m", module_name], stdout=None, stderr=None
                        )
                    while flag_path.exists():
                        time.sleep(1)
                    print(f"[tbot_supervisor] Individual TEST_MODE '{test_name}' complete.")

            if CONTROL_START_FLAG.exists():
                BOT_STATE_PATH.write_text("running", encoding="utf-8")
                print("[tbot_supervisor] CONTROL_START_FLAG detected. Set bot state to 'running'.")
                CONTROL_START_FLAG.unlink(missing_ok=True)

            if CONTROL_STOP_FLAG.exists():
                BOT_STATE_PATH.write_text("idle", encoding="utf-8")
                print("[tbot_supervisor] CONTROL_STOP_FLAG detected. Set bot state to 'idle'.")
                CONTROL_STOP_FLAG.unlink(missing_ok=True)

            if is_time_for_universe_rebuild():
                # Treat universe build as one-off
                if not ensure_singleton("universe_orchestrator.py"):
                    print("[tbot_supervisor] Triggering universe cache rebuild (universe_orchestrator.py)...")
                    processes["universe_orchestrator"] = launch_subprocess(UNIVERSE_ORCHESTRATOR_PATH)
                else:
                    print("[tbot_supervisor] Universe cache rebuild already running.")

            # Restart policy (exclude one-offs; remove finished from tracking)
            to_remove = []
            for name, proc in list(processes.items()):
                if proc.poll() is not None:
                    if name in NON_RESTARTABLE:
                        print(f"[tbot_supervisor] {name} finished (one-off). Not restarting.")
                        to_remove.append(name)
                    else:
                        print(f"[tbot_supervisor] {name} has died. Restarting...")
                        # Find path and restart
                        for t_name, t_path in (launch_targets + persistent_ops + strategy_launchers):
                            if t_name == name:
                                processes[name] = launch_subprocess(t_path)
                                break
            for name in to_remove:
                processes.pop(name, None)

            previous_state = state
            time.sleep(2)

    except KeyboardInterrupt:
        print("[tbot_supervisor] KeyboardInterrupt received, terminating.")

    finally:
        for pname, proc in processes.items():
            try:
                print(f"[tbot_supervisor] Terminating {pname} process...")
                proc.terminate()
            except Exception as e:
                print(f"[tbot_supervisor] Exception terminating {pname}: {e}")
        if 'status_bot_proc' in locals() and status_bot_proc:
            try:
                print("[tbot_supervisor] Terminating status_bot.py process...")
                status_bot_proc.terminate()
            except Exception as e:
                print(f"[tbot_supervisor] Exception terminating status_bot.py: {e}")

if __name__ == "__main__":
    main()
