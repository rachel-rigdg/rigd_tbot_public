# tbot_bot/strategy/strategy_open.py
# summary: Implements opening range breakout strategy with full bi-directional support and updated env references; compresses analysis/monitor window to 1min if TEST_MODE

import time
from datetime import timedelta
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.trading.utils_etf import get_inverse_etf
from tbot_bot.trading.utils_puts import get_put_option
from tbot_bot.trading.utils_shorts import get_short_instrument
from tbot_bot.trading.orders_bot import create_order
from tbot_bot.trading.kill_switch import trigger_shutdown
from tbot_bot.strategy.strategy_meta import StrategyResult
from tbot_bot.trading.risk_bot import validate_trade
from tbot_bot.config.error_handler_bot import handle as handle_error
from tbot_bot.support.decrypt_secrets import decrypt_json
from pathlib import Path

config = get_bot_config()
broker_creds = decrypt_json("broker_credentials")
BROKER_CODE = broker_creds.get("BROKER_CODE", "").lower()

STRAT_OPEN_ENABLED = config["STRAT_OPEN_ENABLED"]
STRAT_OPEN_BUFFER = float(config["STRAT_OPEN_BUFFER"])
OPEN_ANALYSIS_TIME = int(config["OPEN_ANALYSIS_TIME"])
OPEN_BREAKOUT_TIME = int(config["OPEN_BREAKOUT_TIME"])
OPEN_MONITORING_TIME = int(config["OPEN_MONITORING_TIME"])
SHORT_TYPE_OPEN = config["SHORT_TYPE_OPEN"]
ACCOUNT_BALANCE = float(config["ACCOUNT_BALANCE"])
MAX_RISK_PER_TRADE = float(config["MAX_RISK_PER_TRADE"])
DEFAULT_CAPITAL_PER_TRADE = ACCOUNT_BALANCE * MAX_RISK_PER_TRADE
SLEEP_TIME_STR = config["SLEEP_TIME"]

CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def parse_sleep_time(sleep_str):
    try:
        if sleep_str.endswith("s"):
            return float(sleep_str[:-1])
        elif sleep_str.endswith("ms"):
            return float(sleep_str[:-2]) / 1000.0
        else:
            return float(sleep_str)
    except Exception:
        return 1.0

SLEEP_TIME = parse_sleep_time(SLEEP_TIME_STR)

range_data = {}

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

def self_check():
    return STRAT_OPEN_ENABLED and STRAT_OPEN_BUFFER > 0

def analyze_opening_range(start_time, screener_class):
    log_event("strategy_open", "Starting opening range analysis...")
    analysis_minutes = 1 if is_test_mode_active() else OPEN_ANALYSIS_TIME
    deadline = start_time + timedelta(minutes=analysis_minutes)
    screener = screener_class(strategy="open")
    global range_data
    range_data = {}
    while utc_now() < deadline:
        try:
            candidates = screener.run_screen()
        except Exception as e:
            handle_error("strategy_open", "LogicError", e)
            break

        if not candidates:
            log_event("strategy_open", "No valid symbols returned — triggering fallback shutdown")
            trigger_shutdown("No symbols passed screener during open analysis")
            return {}

        for stock in candidates:
            symbol = stock["symbol"]
            price = float(stock["price"])
            if symbol not in range_data:
                range_data[symbol] = {"high": price, "low": price}
            else:
                range_data[symbol]["high"] = max(range_data[symbol]["high"], price)
                range_data[symbol]["low"] = min(range_data[symbol]["low"], price)

        time.sleep(SLEEP_TIME)

    log_event("strategy_open", f"Range data collected for {len(range_data)} symbols.")
    return range_data

def detect_breakouts(start_time, screener_class):
    log_event("strategy_open", "Monitoring for breakouts...")
    trades = []
    breakout_minutes = 1 if is_test_mode_active() else OPEN_BREAKOUT_TIME
    deadline = start_time + timedelta(minutes=breakout_minutes)
    screener = screener_class(strategy="open")
    global range_data
    while utc_now() < deadline:
        try:
            candidates = screener.run_screen()
        except Exception as e:
            handle_error("strategy_open", "LogicError", e)
            break

        if not candidates:
            log_event("strategy_open", "No valid symbols returned during breakout monitoring")
            break

        for stock in candidates:
            symbol = stock["symbol"]
            price = float(stock["price"])

            if symbol not in range_data:
                continue

            high = range_data[symbol]["high"]
            low = range_data[symbol]["low"]
            long_trigger = high * (1 + STRAT_OPEN_BUFFER)
            short_trigger = low * (1 - STRAT_OPEN_BUFFER)

            # Long breakout
            if price > long_trigger:
                if validate_trade(symbol, "buy", DEFAULT_CAPITAL_PER_TRADE):
                    try:
                        result = create_order(
                            ticker=symbol,
                            side="buy",
                            capital=DEFAULT_CAPITAL_PER_TRADE,
                            price=price,
                            stop_loss_pct=0.02,
                            strategy_name="open"
                        )
                        if result:
                            trades.append(result)
                            log_event("strategy_open", f"LONG breakout for {symbol} at {price}")
                    except Exception as e:
                        handle_error("strategy_open", "BrokerError", e)
                range_data.pop(symbol, None)
                time.sleep(SLEEP_TIME)
                continue

            # Short breakout
            if price < short_trigger:
                if SHORT_TYPE_OPEN == "disabled":
                    log_event("strategy_open", f"Short skipped for {symbol} (SHORT_TYPE disabled)")
                elif validate_trade(symbol, "sell", DEFAULT_CAPITAL_PER_TRADE):
                    instrument = None
                    side = "sell"

                    if SHORT_TYPE_OPEN == "InverseETF":
                        instrument = get_inverse_etf(symbol)
                        if not instrument:
                            log_event("strategy_open", f"No inverse ETF mapping for {symbol}, skipping short trade")
                            continue
                        side = "buy"  # Inverse ETF is long position

                    elif SHORT_TYPE_OPEN == "LongPut":
                        instrument = get_put_option(symbol)
                        if not instrument:
                            log_event("strategy_open", f"Put option contract unavailable for {symbol}, skipping short trade")
                            continue
                        side = "buy"

                    elif SHORT_TYPE_OPEN in ("Short", "Synthetic"):
                        short_spec = get_short_instrument(symbol, BROKER_CODE, short_type=SHORT_TYPE_OPEN)
                        if not short_spec:
                            log_event("strategy_open", f"No valid short method for {symbol} on {BROKER_CODE}")
                            continue
                        instrument = short_spec.get("symbol", symbol)
                        side = short_spec.get("side", "sell")

                    else:
                        log_event("strategy_open", f"Unsupported SHORT_TYPE_OPEN: {SHORT_TYPE_OPEN}")
                        continue

                    try:
                        result = create_order(
                            ticker=instrument,
                            side=side,
                            capital=DEFAULT_CAPITAL_PER_TRADE,
                            price=price,
                            stop_loss_pct=0.02,
                            strategy_name="open"
                        )
                        if result:
                            trades.append(result)
                            log_event("strategy_open", f"SHORT breakout for {symbol} at {price} using {instrument}")
                    except Exception as e:
                        handle_error("strategy_open", "BrokerError", e)
                range_data.pop(symbol, None)
                time.sleep(SLEEP_TIME)

        time.sleep(SLEEP_TIME)

    return trades

def run_open_strategy(screener_class):
    if not self_check():
        log_event("strategy_open", "Strategy self_check() failed — skipping.")
        return StrategyResult(skipped=True)

    start_time = utc_now()
    analyze_opening_range(start_time, screener_class)
    trades = detect_breakouts(start_time, screener_class)
    log_event("strategy_open", f"Open strategy completed: {len(trades)} trades placed")
    return StrategyResult(trades=trades, skipped=False)
