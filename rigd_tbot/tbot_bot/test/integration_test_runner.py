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
import importlib
import os
from datetime import datetime, timezone

print(f"[LAUNCH] integration_test_runner.py launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)

PROJECT_ROOT = get_project_root()

# PATCH: Always force load .env if present, even for subprocess (web/Flask)
env_path = Path(PROJECT_ROOT) / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=str(env_path), override=True)
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k] = v

BOT_IDENTITY = get_bot_identity()
CONTROL_DIR = resolve_control_path()
MAX_TEST_TIME = 90  # seconds per test
MAX_STRATEGY_TIME = 60  # seconds per strategy

# Canonical test list — must match test_web.py + static/js/test_ui.js
ALL_TESTS = [
    "integration_test_runner",
    "backtest_engine",
    "broker_sync",
    "broker_trade_stub",
    "coa_consistency",
    "coa_mapping",
    "coa_web_endpoints",
    "env_bot",
    "fallback_logic",
    "holdings_manager",
    "holdings_web_endpoints",
    "ledger_coa_edit",
    "ledger_concurrency",
    "ledger_corruption",
    "ledger_double_entry",
    "ledger_migration",
    "ledger_reconciliation",
    "ledger_schema",
    "ledger_write_failure",
    "logging_format",
    "main_bot",
    "mapping_upsert",
    "opening_balance",
    "screener_credentials",
    "screener_integration",
    "screener_random",
    "strategy_selfcheck",
    "strategy_tuner",
    "symbol_universe_refresh",
    "universe_cache",
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
                    with path.open(encoding="utf-8") as f:
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
    all_flags = list(Path(CONTROL_DIR).glob("test_mode_*.flag"))
    if any(flag.name == "test_mode.flag" for flag in all_flags):
        return None
    for flag in all_flags:
        if flag.name != "test_mode.flag":
            return flag
    return None

def set_test_status(status_dict):
    try:
        status_path = Path(TEST_STATUS_PATH)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with status_path.open("w", encoding="utf-8") as f:
            json.dump(status_dict, f, indent=2)
    except Exception:
        pass

def update_test_status(test_name, status):
    try:
        status_path = Path(TEST_STATUS_PATH)
        if status_path.exists():
            with status_path.open("r", encoding="utf-8") as f:
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
                logf.write(out.decode(errors="replace"))
                logf.flush()
            if err:
                logf.write(err.decode(errors="replace"))
                logf.flush()

def run_subprocess_with_realtime_log(cmd, **kwargs):
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs
    )
    try:
        start = time.monotonic()
        while True:
            if proc.poll() is not None:
                break
            write_log_realtime(proc)
            if time.monotonic() - start > MAX_TEST_TIME:
                proc.kill()
                break
            time.sleep(0.25)
    except Exception:
        proc.kill()
    return proc

def _test_module_map():
    # Centralized mapping for both individual and full-run execution
    return {
        "integration_test_runner": "tbot_bot.test.integration_test_runner",
        "backtest_engine": "tbot_bot.test.test_backtest_engine",
        "broker_sync": "tbot_bot.test.test_broker_sync",
        "broker_trade_stub": "tbot_bot.test.test_broker_trade_stub",
        "coa_consistency": "tbot_bot.test.test_coa_consistency",
        "coa_mapping": "tbot_bot.test.test_coa_mapping",
        "coa_web_endpoints": "tbot_bot.test.test_coa_web_endpoints",
        "env_bot": "tbot_bot.test.test_env_bot",
        "fallback_logic": "tbot_bot.test.test_fallback_logic",
        "holdings_manager": "tbot_bot.test.test_holdings_manager",
        "holdings_web_endpoints": "tbot_bot.test.test_holdings_web_endpoints",
        "ledger_coa_edit": "tbot_bot.test.test_ledger_coa_edit",
        "ledger_concurrency": "tbot_bot.test.test_ledger_concurrency",
        "ledger_corruption": "tbot_bot.test.test_ledger_corruption",
        "ledger_double_entry": "tbot_bot.test.test_ledger_double_entry",
        "ledger_migration": "tbot_bot.test.test_ledger_migration",
        "ledger_reconciliation": "tbot_bot.test.test_ledger_reconciliation",
        "ledger_schema": "tbot_bot.test.test_ledger_schema",
        "ledger_write_failure": "tbot_bot.test.test_ledger_write_failure",
        "logging_format": "tbot_bot.test.test_logging_format",
        "main_bot": "tbot_bot.test.test_main_bot",
        "mapping_upsert": "tbot_bot.test.test_mapping_upsert",
        "opening_balance": "tbot_bot.test.test_opening_balance",
        "screener_credentials": "tbot_bot.test.test_screener_credentials",
        "screener_integration": "tbot_bot.test.test_screener_integration",
        "screener_random": "tbot_bot.test.test_screener_random",
        "strategy_selfcheck": "tbot_bot.test.test_strategy_selfcheck",
        "strategy_tuner": "tbot_bot.test.test_strategy_tuner",
        "symbol_universe_refresh": "tbot_bot.test.test_symbol_universe_refresh",
        "universe_cache": "tbot_bot.test.test_universe_cache",
    }

# --------------------------
# NEW: Strict TEST_MODE fast-path for strategies (surgical addition)
# --------------------------
def _resolve_screener_class():
    """
    Resolve screener class from config; supports dotted path in SCREENER_CLASS_PATH,
    or provider keyword in SCREENER_CLASS. Falls back to FinnhubScreener.
    """
    cfg = get_bot_config()
    dotted = cfg.get("SCREENER_CLASS_PATH") or ""
    if dotted:
        mod, cls = dotted.rsplit(".", 1)
        return getattr(importlib.import_module(mod), cls)
    key = (cfg.get("SCREENER_CLASS") or "").upper()
    if key in ("FINNHUB", "FINNHUB_SCREENER"):
        from tbot_bot.screeners.screeners.finnhub_screener import FinnhubScreener
        return FinnhubScreener
    # Fallback: Finnhub
    from tbot_bot.screeners.screeners.finnhub_screener import FinnhubScreener
    return FinnhubScreener

def _force_test_timing_env():
    os.environ["OPEN_ANALYSIS_TIME"] = "1"
    os.environ["OPEN_BREAKOUT_TIME"] = "1"
    os.environ["OPEN_MONITORING_TIME"] = "1"
    os.environ["MID_ANALYSIS_TIME"] = "1"
    os.environ["MID_MONITORING_TIME"] = "1"
    os.environ["CLOSE_ANALYSIS_TIME"] = "1"
    os.environ["CLOSE_MONITORING_TIME"] = "1"

def _clear_test_timing_env():
    for var in [
        "OPEN_ANALYSIS_TIME", "OPEN_BREAKOUT_TIME", "OPEN_MONITORING_TIME",
        "MID_ANALYSIS_TIME", "MID_MONITORING_TIME",
        "CLOSE_ANALYSIS_TIME", "CLOSE_MONITORING_TIME"
    ]:
        if var in os.environ:
            del os.environ[var]

def _run_strategies_sequentially():
    """
    Immediate sequential execution of open→mid→close with 1-minute windows,
    honoring TEST_MODE semantics and without injecting fallback symbols.
    """
    from tbot_bot.strategy.strategy_open import run_open_strategy
    from tbot_bot.strategy.strategy_mid import run_mid_strategy
    from tbot_bot.strategy.strategy_close import run_close_strategy

    screener_cls = _resolve_screener_class()

    results = {}

    try:
        res_open = run_open_strategy(screener_cls)
        results["open"] = "PASSED" if getattr(res_open, "skipped", False) is False else "NO_TRADES"
    except Exception:
        results["open"] = "ERRORS"
        with open(TEST_LOG_PATH, "a", encoding="utf-8") as logf:
            logf.write(f"[integration_test_runner] Open strategy crashed:\n{traceback.format_exc()}\n")

    try:
        res_mid = run_mid_strategy(screener_cls)
        results["mid"] = "PASSED" if getattr(res_mid, "skipped", False) is False else "NO_TRADES"
    except Exception:
        results["mid"] = "ERRORS"
        with open(TEST_LOG_PATH, "a", encoding="utf-8") as logf:
            logf.write(f"[integration_test_runner] Mid strategy crashed:\n{traceback.format_exc()}\n")

    try:
        res_close = run_close_strategy(screener_cls)
        results["close"] = "PASSED" if getattr(res_close, "skipped", False) is False else "NO_TRADES"
    except Exception:
        results["close"] = "ERRORS"
        with open(TEST_LOG_PATH, "a", encoding="utf-8") as logf:
            logf.write(f"[integration_test_runner] Close strategy crashed:\n{traceback.format_exc()}\n")

    return results
# --------------------------

def run_single_test_module(flag):
    test_name = flag.name.replace("test_mode_", "").replace(".flag", "")
    test_map = _test_module_map()
    module = test_map.get(test_name)
    if module:
        print(f"[integration_test_runner] Detected individual test flag: {flag}. Running {module}")
        update_test_status(test_name, "RUNNING")
        proc = subprocess.Popen(
            ["python3", "-u", "-m", module],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        try:
            proc.wait(timeout=MAX_TEST_TIME)
            write_log_realtime(proc)
            if proc.returncode == 0:
                update_test_status(test_name, "PASSED")
            else:
                update_test_status(test_name, "ERRORS")
        except subprocess.TimeoutExpired:
            proc.kill()
            update_test_status(test_name, "TIMEOUT")
            with open(TEST_LOG_PATH, "a", encoding="utf-8") as logf:
                logf.write(f"[integration_test_runner] Test {test_name} timed out after {MAX_TEST_TIME} seconds.\n")
    else:
        print(f"[integration_test_runner] Unknown test flag or test module: {flag}")
        update_test_status(test_name, "ERRORS")
    _clear_flag(flag)

def run_integration_test():
    set_cwd_and_syspath()

    # If global TEST_MODE flag exists, run the strict sequential strategy test and exit cleanly.
    global_flag = Path(CONTROL_DIR) / "test_mode.flag"
    if global_flag.exists():
        log_event("integration_test", "Global test_mode.flag detected — running open→mid→close sequentially with 1-minute windows.")
        # Force short windows, ensure cleanup afterwards
        try:
            _force_test_timing_env()
            results = _run_strategies_sequentially()
            with open(get_output_path("logs", "integration_test_results.json"), "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)
        finally:
            _clear_flag(global_flag)
            _clear_test_timing_env()
        # Exit clean (hand control back to main process)
        return

    # Otherwise, retain original behavior: orchestrate individual or full test suite.
    flag = detect_individual_test_flag()
    if flag and flag.name != "test_mode.flag":
        run_single_test_module(flag)
        return

    log_event("integration_test", "Starting integration test runner...")

    # Clear logs before running all tests (fix: wrap path with Path)
    try:
        log_path = Path(TEST_LOG_PATH)
        if log_path.exists():
            log_path.unlink()
    except Exception:
        pass

    reset_all_status()

    config = get_bot_config()
    test_map = _test_module_map()

    test_results = {}

    try:
        for test_name in ALL_TESTS:
            try:
                update_test_status(test_name, "RUNNING")
                module = test_map.get(test_name)
                if not module:
                    update_test_status(test_name, "ERRORS")
                    test_results[test_name] = "ERRORS"
                    continue
                flag_path = Path(CONTROL_DIR) / f"test_mode_{test_name}.flag"
                with flag_path.open("w", encoding="utf-8") as f:
                    f.write("1\n")
                proc = subprocess.Popen(
                    ["python3", "-u", "-m", module],
                    cwd=PROJECT_ROOT,
                    env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(PROJECT_ROOT)},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                try:
                    proc.wait(timeout=MAX_TEST_TIME)
                    write_log_realtime(proc)
                    if proc.returncode == 0:
                        update_test_status(test_name, "PASSED")
                        test_results[test_name] = "PASSED"
                    else:
                        update_test_status(test_name, "ERRORS")
                        test_results[test_name] = "ERRORS"
                except subprocess.TimeoutExpired:
                    proc.kill()
                    update_test_status(test_name, "TIMEOUT")
                    test_results[test_name] = "TIMEOUT"
                    with open(TEST_LOG_PATH, "a", encoding="utf-8") as logf:
                        logf.write(f"[integration_test_runner] Test {test_name} timed out after {MAX_TEST_TIME} seconds.\n")
                if flag_path.exists():
                    flag_path.unlink()
                time.sleep(1)
            except Exception:
                update_test_status(test_name, "ERRORS")
                test_results[test_name] = "ERRORS"
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

        with open(get_output_path("logs", "integration_test_results.json"), "w", encoding="utf-8") as f:
            json.dump(test_results, f, indent=2)

    except Exception as e:
        tb = traceback.format_exc()
        log_event("integration_test", f"Fatal error during test: {e}")
        # Mark any RUNNING tests as ERRORS
        try:
            status_path = Path(TEST_STATUS_PATH)
            if status_path.exists():
                with status_path.open("r", encoding="utf-8") as f:
                    status_dict = json.load(f)
            else:
                status_dict = {}
            for test_name in ALL_TESTS:
                if status_dict.get(test_name) == "RUNNING":
                    update_test_status(test_name, "ERRORS")
        except Exception:
            pass
        with open(TEST_LOG_PATH, "a", encoding="utf-8") as logf:
            logf.write("Integration test failed with error:\n" + tb + "\n")
        sys.exit(1)
    finally:
        # Final cleanup: remove any lingering flags (global or individual)
        try:
            gflag = Path(CONTROL_DIR) / "test_mode.flag"
            _clear_flag(gflag)
            for f in Path(CONTROL_DIR).glob("test_mode_*.flag"):
                _clear_flag(f)
        except Exception:
            pass

if __name__ == "__main__":
    run_integration_test()
