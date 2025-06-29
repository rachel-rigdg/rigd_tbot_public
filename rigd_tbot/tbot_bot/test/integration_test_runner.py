# tbot_bot/test/integration_test_runner.py
# Simulates full bot session for integration validation using runtime identity output paths

import sys
import time
import traceback
import json
from pathlib import Path
from dotenv import load_dotenv
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_output_path
from tbot_bot.strategy.strategy_router import route_strategy
from tbot_bot.support.utils_log import log_event
from tbot_bot.runtime.status_bot import bot_status
from tbot_bot.support.utils_identity import get_bot_identity

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

BOT_IDENTITY = get_bot_identity()
CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"

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
        f"{BOT_IDENTITY}_BOT_COA.db",
        f"{BOT_IDENTITY}_BOT_ledger.db",
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
    for flag in CONTROL_DIR.glob("test_mode_*.flag"):
        return flag
    return None

def run_integration_test():
    log_event("integration_test", "Starting integration test runner...")

    config = get_bot_config()
    try:
        sequence = config.get("STRATEGY_SEQUENCE", "open,mid,close").split(",")
        override = config.get("STRATEGY_OVERRIDE")
        strategies = override.split(",") if override and override != "null" else sequence

        for strat in strategies:
            strat = strat.strip().lower()
            log_event("integration_test", f"Triggering strategy: {strat}")
            result = route_strategy(strat)
            if getattr(result, 'skipped', False):
                print(f"Strategy {strat} was skipped or failed to trigger.")
            else:
                print(f"Strategy {strat} executed successfully.")
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
        # Remove global test_mode.flag if present
        _clear_flag(CONTROL_DIR / "test_mode.flag")
        # Remove individual test flag if present
        flag = detect_individual_test_flag()
        if flag:
            _clear_flag(flag)

if __name__ == "__main__":
    run_integration_test()
