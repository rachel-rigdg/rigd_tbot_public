# tbot_bot/test/test_broker_trade_stub.py
# Sends randomized micro-trades to broker to validate order flow, response, and logging
# -------------------------------------------------------------------------------------

import random
import time
from collections import defaultdict
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.trading.orders_bot import create_order
from tbot_bot.trading.instruments import resolve_bearish_instrument
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path

# Load config
config = get_bot_config()
BROKER_NAME = config.get("BROKER_NAME", "ALPACA").upper()
ACCOUNT_BALANCE = float(config.get("ACCOUNT_BALANCE", 100000))
MAX_RISK_PER_TRADE = float(config.get("MAX_RISK_PER_TRADE", 0.01))
CAPITAL_PER_TRADE = ACCOUNT_BALANCE * MAX_RISK_PER_TRADE
TRADE_COUNT = int(config.get("TEST_TRADE_COUNT", 5))
DELAY_BETWEEN_TRADES = float(config.get("TEST_TRADE_DELAY", 2.0))  # seconds

# Sample tickers (prefer low-volatility liquid symbols)
TEST_TICKERS = ["AAPL", "MSFT", "TSLA", "AMD", "NVDA", "SPY", "QQQ"]

# Track per-direction executions to avoid wash trades
executed_sides = defaultdict(set)

def run_trade_stub():
    log_event("test_trade_stub", "Starting randomized trade validation sequence...")

    attempts = 0
    successful = 0

    while successful < TRADE_COUNT and attempts < TRADE_COUNT * 3:
        attempts += 1
        symbol = random.choice(TEST_TICKERS)
        side = random.choice(["buy", "sell"])

        # Prevent wash trade: skip if already traded in opposite direction
        if side in executed_sides[symbol] or ("buy" in executed_sides[symbol] and "sell" in executed_sides[symbol]):
            continue

        price = round(random.uniform(50, 300), 2)

        if side == "sell":
            instrument = resolve_bearish_instrument(symbol, short_type=config.get("SHORT_TYPE_OPEN", "direct"))
            if not instrument:
                log_event("test_trade_stub", f"Skipping short trade — no inverse instrument for {symbol}")
                continue
            exec_symbol = instrument
            exec_side = "sell"
        else:
            exec_symbol = symbol
            exec_side = "buy"

        try:
            result = create_order(
                ticker=exec_symbol,
                side=exec_side,
                capital=CAPITAL_PER_TRADE,
                price=price,
                stop_loss_pct=0.02,
                strategy_name="test_stub"
            )
            if result:
                executed_sides[symbol].add(side)
                log_event("test_trade_stub", f"Trade executed: {result}")
                successful += 1
            else:
                log_event("test_trade_stub", f"No trade result returned for {symbol}")
        except Exception as e:
            log_event("test_trade_stub", f"Trade execution error: {e}", level="error")

        time.sleep(DELAY_BETWEEN_TRADES)

    log_event("test_trade_stub", f"Trade stub sequence completed: {successful} trades executed.")

if __name__ == "__main__":
    run_trade_stub()
