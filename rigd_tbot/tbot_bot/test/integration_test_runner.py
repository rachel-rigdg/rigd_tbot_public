# tbot_bot/test/integration_test_runner.py
# TEST RUNNER. Launched by main.py in TEST_MODE or manually/CI.
# Simulates full bot session. Writes ONLY test logs/artifacts. Never launches or supervises any watcher/worker.

from dotenv import load_dotenv
from pathlib import Path
import sys
import time
import traceback
import json
import os

# Load .env
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_output_path
from tbot_bot.strategy.strategy_router import route_strategy
from tbot_bot.support.utils_log import log_event
from tbot_bot.runtime.status_bot import bot_status
from tbot_bot.support.utils_identity import get_bot_identity

CONTROL_DIR = Path(__file__).resolve().parents[2] / "tbot_bot" / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"
TEST_MODE_LOG = get_output_path("logs", "test_mode.log")
BOT_IDENTITY = get_bot_identity()

def check_output_artifacts():
    """Verify output files exist after test session."""
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
    """Check if expected bot ledger exports exist."""
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

def run_integration_test():
    """Run full test strategy sequence and verify artifacts. Writes to test_mode.log only."""
    # Log test run start
    with open(TEST_MODE_LOG, "a") as logf:
        logf.write("[integration_test_runner] Starting integration test runner...\n")
    log_event("integration_test", "Starting integration test runner...")

    config = get_bot_config()
    try:
        # Force test sequence: always run open, mid, close (regardless of STRATEGY_SEQUENCE)
        test_strategies = ["open", "mid", "close"]
        for strat in test_strategies:
            log_event("integration_test", f"Triggering strategy: {strat}")
            with open(TEST_MODE_LOG, "a") as logf:
                logf.write(f"[integration_test_runner] Triggering strategy: {strat}\n")
            result = route_strategy(strat)
            if getattr(result, 'skipped', False):
                msg = f"Strategy {strat} was skipped or failed to trigger."
                print(msg)
                with open(TEST_MODE_LOG, "a") as logf:
                    logf.write(f"[integration_test_runner] {msg}\n")
            else:
                msg = f"Strategy {strat} executed successfully."
                print(msg)
                with open(TEST_MODE_LOG, "a") as logf:
                    logf.write(f"[integration_test_runner] {msg}\n")
            time.sleep(1)

        print("\nVerifying output artifacts...\n")
        with open(TEST_MODE_LOG, "a") as logf:
            logf.write("[integration_test_runner] Verifying output artifacts...\n")
        check_output_artifacts()
        check_ledger_exports()

        print("\nFinal Bot Status:")
        for key, value in bot_status.to_dict().items():
            print(f"  {key}: {value}")

        log_event("integration_test", "Integration test completed.")
        with open(TEST_MODE_LOG, "a") as logf:
            logf.write("[integration_test_runner] Integration test completed.\n")

    except Exception as e:
        tb = traceback.format_exc()
        log_event("integration_test", f"Fatal error during test: {e}")
        with open(TEST_MODE_LOG, "a") as logf:
            logf.write(f"[integration_test_runner] Integration test failed with error:\n{tb}\n")
        print("Integration test failed with error:\n", tb)
        # Clean up test_mode.flag even on error
        if TEST_MODE_FLAG.exists():
            TEST_MODE_FLAG.unlink()
        sys.exit(1)

    # Clean up test_mode.flag at end of run
    if TEST_MODE_FLAG.exists():
        TEST_MODE_FLAG.unlink()
        with open(TEST_MODE_LOG, "a") as logf:
            logf.write("[integration_test_runner] test_mode.flag deleted at test completion.\n")

if __name__ == "__main__":
    run_integration_test()
