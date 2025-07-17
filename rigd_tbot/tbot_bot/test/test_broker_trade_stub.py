# tbot_bot/test/test_broker_trade_stub.py
# Sends randomized micro-trades to broker to validate order flow, response, and logging
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.

import sys
from pathlib import Path

TEST_FLAG_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode_broker_trade_stub.flag"
RUN_ALL_FLAG = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "test_mode.flag"

def safe_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

if __name__ == "__main__":
    if not (TEST_FLAG_PATH.exists() or RUN_ALL_FLAG.exists()):
        safe_print("[test_broker_trade_stub.py] Individual test flag not present. Exiting.")
        sys.exit(0)

import random
import time
from collections import defaultdict
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.trading.orders_bot import create_order
from tbot_bot.trading.instruments import resolve_bearish_instrument
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.decrypt_secrets import decrypt_json

config = get_bot_config()
broker_creds = decrypt_json("broker_credentials")
BROKER_CODE = broker_creds.get("BROKER_CODE", "").upper()
ACCOUNT_BALANCE = float(config.get("ACCOUNT_BALANCE", 100.00))
MAX_RISK_PER_TRADE = float(config.get("MAX_RISK_PER_TRADE", 0.01))
CAPITAL_PER_TRADE = ACCOUNT_BALANCE * MAX_RISK_PER_TRADE
TRADE_COUNT = int(config.get("TEST_TRADE_COUNT", 5))
DELAY_BETWEEN_TRADES = float(config.get("TEST_TRADE_DELAY", 2.0))  # seconds

TEST_TICKERS = ["AAPL", "MSFT", "TSLA", "AMD", "NVDA", "SPY", "QQQ"]

executed_sides = defaultdict(set)

def run_trade_stub():
    safe_print("[test_broker_trade_stub] Starting randomized trade validation sequence...")
    log_event("test_trade_stub", "Starting randomized trade validation sequence...")

    attempts = 0
    successful = 0

    while successful < TRADE_COUNT and attempts < TRADE_COUNT * 3:
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
                log_event("test_trade_stub", f"Skipping short trade — no inverse instrument for {symbol}")
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
                log_event("test_trade_stub", msg)
                successful += 1
            else:
                safe_print(f"[test_broker_trade_stub] No trade result returned for {symbol}")
                log_event("test_trade_stub", f"No trade result returned for {symbol}")
        except Exception as e:
            err_msg = f"Trade execution error: {e}"
            safe_print(f"[test_broker_trade_stub] {err_msg}")
            log_event("test_trade_stub", err_msg, level="error")

        time.sleep(DELAY_BETWEEN_TRADES)

    safe_print(f"[test_broker_trade_stub] Trade stub sequence completed: {successful} trades executed.")
    log_event("test_trade_stub", f"Trade stub sequence completed: {successful} trades executed.")

def run_test():
    run_trade_stub()
    if TEST_FLAG_PATH.exists():
        TEST_FLAG_PATH.unlink()

if __name__ == "__main__":
    run_test()
