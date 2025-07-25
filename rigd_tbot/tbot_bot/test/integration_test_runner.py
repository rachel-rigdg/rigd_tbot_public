# tbot_bot/test/integration_test_runner.py
# Simulates full bot session for integration validation using runtime identity output paths

import sys
import time
import traceback
import json
from pathlib import Path
from dotenv import load_dotenv
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_output_path, resolve_control_path, get_project_root
from tbot_bot.strategy.strategy_router import route_strategy
from tbot_bot.support.utils_log import log_event
from tbot_bot.runtime.status_bot import bot_status
from tbot_bot.support.utils_identity import get_bot_identity
import subprocess
import os

load_dotenv(dotenv_path=str(get_project_root() / ".env"))

BOT_IDENTITY = get_bot_identity()
CONTROL_DIR = resolve_control_path()
PROJECT_ROOT = get_project_root()
MAX_STRATEGY_TIME = 60  # seconds per strategy

ALL_TESTS = [
    "broker_sync",
    "coa_mapping",
    "universe_cache",
    "strategy_selfcheck",
    "screener_random",
    "screener_integration",
    "main_bot",
    "ledger_schema",
    "env_bot",
    "coa_web_endpoints",
    "coa_consistency",
    "broker_trade_stub",
    "backtest_engine",
    "logging_format",
    "fallback_logic",
    "holdings_manager"
]
TEST_STATUS_PATH = get_output_path("logs", "test_status.json")
TEST_LOG_PATH = get_output_path("logs", "test_mode.log")

def set_cwd_and_syspath():
    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

def check_output_artifacts():
    files = [
        get_output_path("summaries", f"{BOT_IDENTITY}_BOT_daily_summary.json"),
        get_output_path("trades", f"{BOT_IDENTITY}_BOT_trade_history.json"),
        get_output_path("trades", f"{BOT_IDENTITY}_BOT_trade_history.csv"),
    ]
    for file in files:
        path = Path(file)
        if not path.exists():
            print(f"Missing output file: {file}")
        else:
            print(f"Found output file: {file}")
            if path.suffix == ".json":
                try:
                    with path.open() as f:
                        data = json.load(f)
                        if isinstance(data, list) and data:
                            print(f"   → {len(data)} entries")
                        elif isinstance(data, dict):
                            print(f"   → Keys: {list(data.keys())}")
                except Exception as e:
                    print(f"   Error parsing JSON: {e}")

def check_ledger_exports():
    ledgers = [
        f"{BOT_IDENTITY}_BOT_ledger.db",
        f"{BOT_IDENTITY}_BOT_COA.db",
        f"{BOT_IDENTITY}_BOT_FLOAT_ledger.db",
    ]
    for name in ledgers:
        path = Path(get_output_path("ledgers", name))
        if not path.exists():
            print(f"Ledger not found: {path}")
        else:
            size = path.stat().st_size
            print(f"Ledger found: {path} → {size} bytes")

def _clear_flag(flag_path):
    try:
        if flag_path.exists():
            flag_path.unlink()
    except Exception:
        pass

def detect_individual_test_flag():
    all_flags = list(CONTROL_DIR.glob("test_mode_*.flag"))
    if any(flag.name == "test_mode.flag" for flag in all_flags):
        return None
    for flag in all_flags:
        if flag.name != "test_mode.flag":
            return flag
    return None

def set_test_status(status_dict):
    try:
        os.makedirs(os.path.dirname(TEST_STATUS_PATH), exist_ok=True)
        with open(TEST_STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(status_dict, f, indent=2)
    except Exception:
        pass

def update_test_status(test_name, status):
    try:
        if os.path.exists(TEST_STATUS_PATH):
            with open(TEST_STATUS_PATH, "r", encoding="utf-8") as f:
                status_dict = json.load(f)
        else:
            status_dict = {t: "" for t in ALL_TESTS}
        status_dict[test_name] = status
        set_test_status(status_dict)
    except Exception:
        pass

def reset_all_status():
    set_test_status({t: "QUEUED" for t in ALL_TESTS})

def write_log_realtime(proc):
    with open(TEST_LOG_PATH, "a", encoding="utf-8") as logf:
        while True:
            out = proc.stdout.readline()
            err = proc.stderr.readline()
            if not out and not err and proc.poll() is not None:
                break
            if out:
                logf.write(out.decode())
                logf.flush()
            if err:
                logf.write(err.decode())
                logf.flush()

def run_subprocess_with_realtime_log(cmd, **kwargs):
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs
    )
    write_log_realtime(proc)
    proc.wait()
    return proc

def run_single_test_module(flag):
    test_name = flag.name.replace("test_mode_", "").replace(".flag", "")
    test_map = {
        "broker_sync": "tbot_bot.test.test_broker_sync",
        "coa_mapping": "tbot_bot.test.test_coa_mapping",
        "universe_cache": "tbot_bot.test.test_universe_cache",
        "strategy_selfcheck": "tbot_bot.test.test_strategy_selfcheck",
        "screener_random": "tbot_bot.test.test_screener_random",
        "screener_integration": "tbot_bot.test.test_screener_integration",
        "main_bot": "tbot_bot.test.test_main_bot",
        "ledger_schema": "tbot_bot.test.test_ledger_schema",
        "env_bot": "tbot_bot.test.test_env_bot",
        "coa_web_endpoints": "tbot_bot.test.test_coa_web_endpoints",
        "coa_consistency": "tbot_bot.test.test_coa_consistency",
        "broker_trade_stub": "tbot_bot.test.test_broker_trade_stub",
        "backtest_engine": "tbot_bot.test.test_backtest_engine",
        "logging_format": "tbot_bot.test.test_logging_format",
        "fallback_logic": "tbot_bot.test.strategies.test_fallback_logic",
        "holdings_manager": "tbot_bot.test.test_holdings_manager"
    }
    module = test_map.get(test_name)
    if module:
        print(f"[integration_test_runner] Detected individual test flag: {flag}. Running {module}")
        update_test_status(test_name, "RUNNING")
        proc = run_subprocess_with_realtime_log(
            ["python3", "-u", "-m", module],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)}
        )
        if proc.returncode == 0:
            update_test_status(test_name, "PASSED")
        else:
            update_test_status(test_name, "ERRORS")
    else:
        print(f"[integration_test_runner] Unknown test flag or test module: {flag}")
        update_test_status(test_name, "ERRORS")
    _clear_flag(flag)

def run_integration_test():
    set_cwd_and_syspath()
    flag = detect_individual_test_flag()
    if flag and flag.name != "test_mode.flag":
        run_single_test_module(flag)
        return

    log_event("integration_test", "Starting integration test runner...")

    reset_all_status()

    config = get_bot_config()
    test_map = {
        "broker_sync": "tbot_bot.test.test_broker_sync",
        "coa_mapping": "tbot_bot.test.test_coa_mapping",
        "universe_cache": "tbot_bot.test.test_universe_cache",
        "strategy_selfcheck": "tbot_bot.test.test_strategy_selfcheck",
        "screener_random": "tbot_bot.test.test_screener_random",
        "screener_integration": "tbot_bot.test.test_screener_integration",
        "main_bot": "tbot_bot.test.test_main_bot",
        "ledger_schema": "tbot_bot.test.test_ledger_schema",
        "env_bot": "tbot_bot.test.test_env_bot",
        "coa_web_endpoints": "tbot_bot.test.test_coa_web_endpoints",
        "coa_consistency": "tbot_bot.test.test_coa_consistency",
        "broker_trade_stub": "tbot_bot.test.test_broker_trade_stub",
        "backtest_engine": "tbot_bot.test.test_backtest_engine",
        "logging_format": "tbot_bot.test.test_logging_format",
        "fallback_logic": "tbot_bot.test.strategies.test_fallback_logic",
        "holdings_manager": "tbot_bot.test.test_holdings_manager"
    }

    try:
        for test_name in ALL_TESTS:
            try:
                update_test_status(test_name, "RUNNING")
                module = test_map.get(test_name)
                if not module:
                    update_test_status(test_name, "ERRORS")
                    continue
                flag_path = CONTROL_DIR / f"test_mode_{test_name}.flag"
                with open(flag_path, "w") as f:
                    f.write("1\n")
                proc = subprocess.Popen(
                    ["python3", "-u", "-m", module],
                    cwd=PROJECT_ROOT,
                    env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                write_log_realtime(proc)
                proc.wait()
                if proc.returncode == 0:
                    update_test_status(test_name, "PASSED")
                else:
                    update_test_status(test_name, "ERRORS")
                if flag_path.exists():
                    flag_path.unlink()
                time.sleep(1)
            except Exception as test_exc:
                update_test_status(test_name, "ERRORS")
                tb_str = traceback.format_exc()
                with open(TEST_LOG_PATH, "a", encoding="utf-8") as logf:
                    logf.write(f"[integration_test_runner] Test {test_name} crashed:\n{tb_str}\n")

        print("\nVerifying output artifacts...\n")
        check_output_artifacts()
        check_ledger_exports()

        print("\nFinal Bot Status:")
        for key, value in bot_status.to_dict().items():
            print(f"  {key}: {value}")

        log_event("integration_test", "Integration test completed.")

    except Exception as e:
        tb = traceback.format_exc()
        log_event("integration_test", f"Fatal error during test: {e}")
        for test_name in ALL_TESTS:
            if os.path.exists(TEST_STATUS_PATH):
                with open(TEST_STATUS_PATH, "r", encoding="utf-8") as f:
                    status_dict = json.load(f)
            else:
                status_dict = {}
            if status_dict.get(test_name) == "RUNNING":
                update_test_status(test_name, "ERRORS")
        with open(TEST_LOG_PATH, "a", encoding="utf-8") as logf:
            logf.write("Integration test failed with error:\n" + tb + "\n")
        sys.exit(1)
    finally:
        flag = CONTROL_DIR / "test_mode.flag"
        if flag.exists():
            flag.unlink()

if __name__ == "__main__":
    run_integration_test()
