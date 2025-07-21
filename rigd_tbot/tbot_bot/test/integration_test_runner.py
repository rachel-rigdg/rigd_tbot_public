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

def run_single_test_module(flag):
    test_name = flag.name.replace("test_mode_", "").replace(".flag", "")
    test_map = {
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
        "fallback_logic": "tbot_bot.test.strategies.test_fallback_logic"
    }
    module = test_map.get(test_name)
    if module:
        print(f"[integration_test_runner] Detected individual test flag: {flag}. Running {module}")
        subprocess.run(
            ["python3", "-u", "-m", module],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)},
        )
    else:
        print(f"[integration_test_runner] Unknown test flag or test module: {flag}")
    _clear_flag(flag)

def run_strategy_with_timeout(strat):
    log_event("integration_test", f"Triggering strategy: {strat}")
    # Run strategy in subprocess with timeout
    try:
        proc = subprocess.run(
            [sys.executable, "-c", f"from tbot_bot.strategy.strategy_router import route_strategy; route_strategy(override='{strat}')"],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)},
            timeout=MAX_STRATEGY_TIME,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"Strategy {strat} failed with return code {proc.returncode}")
            print(proc.stdout)
            print(proc.stderr)
        else:
            print(f"Strategy {strat} executed successfully.")
    except subprocess.TimeoutExpired:
        print(f"Strategy {strat} timed out after {MAX_STRATEGY_TIME} seconds.")
        log_event("integration_test", f"Strategy {strat} timed out after {MAX_STRATEGY_TIME} seconds")
    except Exception as e:
        print(f"Strategy {strat} failed with exception: {e}")
        log_event("integration_test", f"Strategy {strat} failed with exception: {e}")

def run_integration_test():
    set_cwd_and_syspath()
    flag = detect_individual_test_flag()
    if flag and flag.name != "test_mode.flag":
        run_single_test_module(flag)
        return

    log_event("integration_test", "Starting integration test runner...")

    config = get_bot_config()
    try:
        sequence = config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")
        override = config.get("STRATEGY_OVERRIDE")
        strategies = override.split(",") if override and override != "null" else sequence

        for strat in strategies:
            strat = strat.strip().lower()
            run_strategy_with_timeout(strat)
            time.sleep(1)

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
        print("Integration test failed with error:\n", tb)
        sys.exit(1)
    finally:
        _clear_flag(CONTROL_DIR / "test_mode.flag")

if __name__ == "__main__":
    run_integration_test()
