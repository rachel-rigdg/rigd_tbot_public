# tbot_bot/test/test_broker_trade_stub.py
# Sends randomized micro-trades to broker to validate order flow, response, and logging
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import sys
import random
import time
from collections import defaultdict
from pathlib import Path
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.trading.orders_bot import create_order
from tbot_bot.trading.instruments import resolve_bearish_instrument
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.support.path_resolver import get_output_path, get_project_root, resolve_control_path
import os

MAX_TEST_TIME = 90  # seconds per test

CONTROL_DIR = resolve_control_path()
TEST_FLAG_PATH = CONTROL_DIR / "test_mode_broker_trade_stub.flag"
RUN_ALL_FLAG = CONTROL_DIR / "test_mode.flag"
LOGFILE = get_output_path("logs", "test_mode.log")
PROJECT_ROOT = get_project_root()

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        log_event("test_broker_trade_stub", msg, logfile=LOGFILE)
    except Exception:
        pass

def set_cwd_and_syspath():
    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

# Patch: Soft-import get_synthetic_short for import dependency (instruments.py may require it)
try:
    from tbot_bot.trading.utils_shorts import get_synthetic_short
except ImportError:
    def get_synthetic_short(*a, **kw):
        return None

if __name__ == "__main__":
    set_cwd_and_syspath()
    if not (Path(TEST_FLAG_PATH).exists() or Path(RUN_ALL_FLAG).exists()):
        safe_print("[test_broker_trade_stub.py] Individual test flag not present. Exiting.")
        sys.exit(0)

    config = get_bot_config()
    broker_creds = decrypt_json("broker_credentials")
    BROKER_CODE = broker_creds.get("BROKER_CODE", "").upper()
    ACCOUNT_BALANCE = float(config.get("ACCOUNT_BALANCE", 100.00))
    MAX_RISK_PER_TRADE = float(config.get("MAX_RISK_PER_TRADE", 0.01))
    CAPITAL_PER_TRADE = ACCOUNT_BALANCE * MAX_RISK_PER_TRADE
    TRADE_COUNT = int(config.get("TEST_TRADE_COUNT", 5))
    DELAY_BETWEEN_TRADES = float(config.get("TEST_TRADE_DELAY", 2.0))

    TEST_TICKERS = ["AAPL", "MSFT", "TSLA", "AMD", "NVDA", "SPY", "QQQ"]
    executed_sides = defaultdict(set)
    _status = ["PASSED"]  # Mutable container workaround

    def run_trade_stub():
        safe_print("[test_broker_trade_stub] Starting randomized trade validation sequence...")

        attempts = 0
        successful = 0
        start_time = time.time()

        while successful < TRADE_COUNT and attempts < TRADE_COUNT * 3:
            # Enforce global timeout
            if (time.time() - start_time) > MAX_TEST_TIME:
                safe_print(f"[test_broker_trade_stub] TIMEOUT: test exceeded {MAX_TEST_TIME} seconds")
                _status[0] = "TIMEOUT"
                break

            attempts += 1
            symbol = random.choice(TEST_TICKERS)
            side = random.choice(["buy", "sell"])

            if side in executed_sides[symbol] or ("buy" in executed_sides[symbol] and "sell" in executed_sides[symbol]):
                continue

            price = round(random.uniform(50, 300), 2)

            if side == "sell":
                instrument = resolve_bearish_instrument(symbol, short_type=config.get("SHORT_TYPE_OPEN", "direct"))
                if not instrument:
                    safe_print(f"[test_broker_trade_stub] Skipping short trade — no inverse instrument for {symbol}")
                    continue
                exec_symbol = instrument
                exec_side = "sell"
            else:
                exec_symbol = symbol
                exec_side = "buy"

            try:
                result = create_order(
                    symbol=exec_symbol,
                    side=exec_side,
                    capital=CAPITAL_PER_TRADE,
                    price=price,
                    stop_loss_pct=0.02,
                    strategy="test_stub"
                )
                if result:
                    executed_sides[symbol].add(side)
                    msg = f"Trade executed: {result}"
                    safe_print(f"[test_broker_trade_stub] {msg}")
                    successful += 1
                else:
                    safe_print(f"[test_broker_trade_stub] No trade result returned for {symbol}")
                    _status[0] = "ERRORS"
            except Exception as e:
                err_msg = f"Trade execution error: {e}"
                safe_print(f"[test_broker_trade_stub] {err_msg}")
                _status[0] = "ERRORS"

            time.sleep(DELAY_BETWEEN_TRADES)

        safe_print(f"[test_broker_trade_stub] Trade stub sequence completed: {successful} trades executed.")
        safe_print(f"[test_broker_trade_stub] FINAL RESULT: {_status[0] if _status[0] != 'PASSED' or successful < TRADE_COUNT else 'PASSED'}")

    def run_test():
        run_trade_stub()
        if Path(TEST_FLAG_PATH).exists():
            Path(TEST_FLAG_PATH).unlink()

    run_test()
