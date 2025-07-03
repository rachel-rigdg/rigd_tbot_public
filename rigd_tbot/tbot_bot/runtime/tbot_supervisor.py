# tbot_bot/runtime/tbot_supervisor.py
# Central phase/process supervisor for TradeBot.
# Responsible for all phase transitions, persistent monitoring, and launching all watcher/worker/test runner processes.
# Only launched by main.py after successful provisioning/bootstrapping and transition to operational state.
# No watcher/worker/test runner is ever launched except by this supervisor.

import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from tbot_bot.support import path_resolver

ROOT_DIR = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT_DIR / "tbot_bot" / "control"
BOT_STATE_PATH = CONTROL_DIR / "bot_state.txt"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"
CONTROL_START_FLAG = CONTROL_DIR / "control_start.flag"
CONTROL_STOP_FLAG = CONTROL_DIR / "control_stop.flag"

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
SYMBOL_UNIVERSE_REFRESH_PATH = path_resolver.resolve_runtime_script_path("symbol_universe_refresh.py")
INTEGRATION_TEST_RUNNER_PATH = path_resolver.resolve_runtime_script_path("integration_test_runner.py")

UNIVERSE_TIMESTAMP_PATH = ROOT_DIR / "tbot_bot" / "output" / "screeners" / "symbol_universe.json"
REBUILD_DELAY_HOURS = 4

def read_env_var(key, default=None):
    from tbot_bot.config.env_bot import load_env_bot_config
    env = load_env_bot_config()
    return env.get(key, default)

def parse_utc_time(timestr):
    h, m = map(int, timestr.split(":"))
    return h, m

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

def is_time_for_universe_rebuild():
    # Always triggers if file does not exist
    if not UNIVERSE_TIMESTAMP_PATH.exists():
        return True
    try:
        import json
        data = json.load(open(UNIVERSE_TIMESTAMP_PATH, "r"))
        build_time_str = data.get("build_timestamp_utc")
        if build_time_str:
            from datetime import datetime, timezone
            if build_time_str.endswith("Z"):
                build_time_str = build_time_str.replace("Z", "+00:00")
            build_time = datetime.fromisoformat(build_time_str)
        else:
            build_time = datetime.utcfromtimestamp(UNIVERSE_TIMESTAMP_PATH.stat().st_mtime)
    except Exception:
        build_time = datetime.utcfromtimestamp(UNIVERSE_TIMESTAMP_PATH.stat().st_mtime)
    now = datetime.utcnow()
    market_close_str = read_env_var("MARKET_CLOSE_UTC", "21:00")
    market_close_hour, market_close_minute = parse_utc_time(market_close_str)
    today_close = now.replace(hour=market_close_hour, minute=market_close_minute, second=0, microsecond=0)
    if now < today_close:
        last_close = today_close - timedelta(days=1)
    else:
        last_close = today_close
    scheduled_time = last_close + timedelta(hours=REBUILD_DELAY_HOURS)
    return now >= scheduled_time and build_time < scheduled_time

def main():
    print("[tbot_supervisor] Starting TradeBot phase supervisor.")
    processes = {}

    launch_targets = [
        ("status_bot", STATUS_BOT_PATH),
        ("watchdog_bot", WATCHDOG_BOT_PATH),
        ("strategy_router", STRATEGY_ROUTER_PATH),
        ("strategy_open", STRATEGY_OPEN_PATH),
        ("strategy_mid", STRATEGY_MID_PATH),
        ("strategy_close", STRATEGY_CLOSE_PATH),
        ("risk_module", RISK_MODULE_PATH),
        ("kill_switch", KILL_SWITCH_PATH),
        ("log_rotation", LOG_ROTATION_PATH),
        ("trade_logger", TRADE_LOGGER_PATH),
        ("status_logger", STATUS_LOGGER_PATH)
    ]

    last_universe_rebuild = None

    # State persistence: read last non-transitional state (idle/running/etc)
    persistent_state = None
    if BOT_STATE_PATH.exists():
        persistent_state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
        if persistent_state not in ("idle", "running", "started", "trading", "monitoring", "analyzing", "updating", "stopped"):
            persistent_state = "idle"

    for name, path in launch_targets:
        script_name = os.path.basename(str(path))
        if not ensure_singleton(script_name):
            print(f"[tbot_supervisor] Launching {script_name}...")
            processes[name] = launch_subprocess(path)
        else:
            print(f"[tbot_supervisor] {script_name} already running.")

    try:
        while True:
            state = read_bot_state()
            if state in ("shutdown", "shutdown_triggered", "error"):
                print(f"[tbot_supervisor] Detected shutdown/error state: {state}. Terminating subprocesses and exiting.")
                break

            if TEST_MODE_FLAG.exists():
                print("[tbot_supervisor] Global TEST_MODE flag detected. Launching integration_test_runner.py...")
                if not ensure_singleton("integration_test_runner.py"):
                    processes["test_runner"] = launch_subprocess(INTEGRATION_TEST_RUNNER_PATH)
                while TEST_MODE_FLAG.exists():
                    time.sleep(1)
                print("[tbot_supervisor] Global TEST_MODE complete. Test runner finished.")

            # Handle individual test flags (run one at a time)
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

            # Automatic universe rebuild 4 hours after market close
            if is_time_for_universe_rebuild():
                if not ensure_singleton("symbol_universe_refresh.py"):
                    print("[tbot_supervisor] Triggering universe cache rebuild (symbol_universe_refresh.py)...")
                    processes["symbol_universe_refresh"] = launch_subprocess(SYMBOL_UNIVERSE_REFRESH_PATH)
                    last_universe_rebuild = time.time()
                else:
                    print("[tbot_supervisor] Universe cache rebuild already running.")

            # On restart, if last persistent_state is 'running', restore 'running'
            if persistent_state == "running" and state != "running" and state == "idle":
                BOT_STATE_PATH.write_text("running", encoding="utf-8")
                print("[tbot_supervisor] Restored bot state to 'running' after restart.")

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

if __name__ == "__main__":
    main()
