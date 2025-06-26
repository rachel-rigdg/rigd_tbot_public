# tbot_bot/strategy/strategy_close.py
# summary: Implements Late-day momentum/fade strategy with VIX gating and bi-directional logic; compresses analysis/monitor window to 1min if TEST_MODE

import time
from datetime import timedelta
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.trading.utils_etf import get_inverse_etf
from tbot_bot.trading.utils_puts import get_put_option
from tbot_bot.trading.utils_shorts import get_short_instrument
from tbot_bot.trading.orders_bot import create_order
from tbot_bot.strategy.strategy_meta import StrategyResult
from tbot_bot.enhancements.vix_gatekeeper import is_vix_above_threshold
from tbot_bot.enhancements.imbalance_scanner_ibkr import is_trade_blocked_by_imbalance
from tbot_bot.enhancements.ticker_blocklist import is_ticker_blocked
from tbot_bot.trading.kill_switch import trigger_shutdown
from tbot_bot.trading.risk_bot import validate_trade
from tbot_bot.config.error_handler_bot import handle as handle_error
from tbot_bot.support.decrypt_secrets import decrypt_json
from pathlib import Path

config = get_bot_config()
broker_creds = decrypt_json("broker_credentials")
BROKER_CODE = broker_creds.get("BROKER_CODE", "").lower()

STRAT_CLOSE_ENABLED = config["STRAT_CLOSE_ENABLED"]
CLOSE_ANALYSIS_TIME = int(config["CLOSE_ANALYSIS_TIME"])
CLOSE_MONITORING_TIME = int(config["CLOSE_MONITORING_TIME"])
VIX_THRESHOLD = float(config["STRAT_CLOSE_VIX_THRESHOLD"])
SHORT_TYPE_CLOSE = config["SHORT_TYPE_CLOSE"]
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

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

def self_check():
    return STRAT_CLOSE_ENABLED and VIX_THRESHOLD >= 0

def analyze_closing_signals(start_time, screener_class):
    log_event("strategy_close", "Starting EOD momentum/fade analysis...")
    analysis_minutes = 1 if is_test_mode_active() else CLOSE_ANALYSIS_TIME
    deadline = start_time + timedelta(minutes=analysis_minutes)
    signals = []

    if not is_vix_above_threshold(VIX_THRESHOLD) and not is_test_mode_active():
        log_event("strategy_close", "VIX filter blocked strategy.")
        return signals

    screener = screener_class(strategy="close")
    while utc_now() < deadline:
        try:
            screener_data = screener.run_screen(limit=50)
        except Exception as e:
            handle_error("strategy_close", "LogicError", e)
            break

        if not screener_data:
            log_event("strategy_close", "No symbols passed filter — triggering fallback kill-switch.")
            trigger_shutdown()
            return []

        for stock in screener_data:
            symbol = stock["symbol"]
            price = float(stock["price"])
            high = float(stock.get("high", 0))
            low = float(stock.get("low", 0))

            if high <= 0 or low <= 0 or price <= 0:
                continue

            if is_ticker_blocked(symbol):
                continue

            range_mid = (high + low) / 2
            if price > high * 0.995:
                direction = "buy"
            elif price < range_mid * 0.9:
                direction = "sell"
            else:
                continue

            signals.append({
                "symbol": symbol,
                "price": price,
                "side": direction,
                "high": high,
                "low": low
            })

        time.sleep(SLEEP_TIME)

    log_event("strategy_close", f"EOD signals found: {len(signals)}")
    return signals

def monitor_closing_trades(signals, start_time):
    log_event("strategy_close", "Monitoring EOD trades...")
    trades = []
    monitoring_minutes = 1 if is_test_mode_active() else CLOSE_MONITORING_TIME
    deadline = start_time + timedelta(minutes=monitoring_minutes)

    for signal in signals:
        if utc_now() >= deadline:
            break

        symbol = signal["symbol"]
        side = signal["side"]
        price = signal["price"]

        try:
            if side == "buy":
                if validate_trade(symbol, "buy", DEFAULT_CAPITAL_PER_TRADE):
                    result = create_order(
                        ticker=symbol,
                        side="buy",
                        capital=DEFAULT_CAPITAL_PER_TRADE,
                        price=price,
                        stop_loss_pct=0.02,
                        strategy_name="close"
                    )
                    if result:
                        trades.append(result)
            elif side == "sell":
                if SHORT_TYPE_CLOSE == "disabled":
                    log_event("strategy_close", f"Short skipped for {symbol} (SHORT_TYPE disabled)")
                elif validate_trade(symbol, "sell", DEFAULT_CAPITAL_PER_TRADE):
                    instrument = None
                    side_exec = "sell"

                    if SHORT_TYPE_CLOSE == "InverseETF":
                        instrument = get_inverse_etf(symbol)
                        if not instrument:
                            log_event("strategy_close", f"No inverse ETF mapping for {symbol}, skipping short trade")
                            continue
                        side_exec = "buy"

                    elif SHORT_TYPE_CLOSE == "LongPut":
                        instrument = get_put_option(symbol)
                        if not instrument:
                            log_event("strategy_close", f"Put option contract unavailable for {symbol}, skipping short trade")
                            continue
                        side_exec = "buy"

                    elif SHORT_TYPE_CLOSE in ("Short", "Synthetic"):
                        short_spec = get_short_instrument(symbol, BROKER_CODE, short_type=SHORT_TYPE_CLOSE)
                        if not short_spec:
                            log_event("strategy_close", f"No valid short method for {symbol} on {BROKER_CODE}")
                            continue
                        instrument = short_spec.get("symbol", symbol)
                        side_exec = short_spec.get("side", "sell")

                    else:
                        log_event("strategy_close", f"Unsupported SHORT_TYPE_CLOSE: {SHORT_TYPE_CLOSE}")
                        continue

                    result = create_order(
                        ticker=instrument,
                        side=side_exec,
                        capital=DEFAULT_CAPITAL_PER_TRADE,
                        price=price,
                        stop_loss_pct=0.02,
                        strategy_name="close"
                    )
                    if result:
                        trades.append(result)
        except Exception as e:
            handle_error("strategy_close", "BrokerError", e)

        time.sleep(SLEEP_TIME)

    log_event("strategy_close", f"Trades completed: {len(trades)}")
    return trades

def run_close_strategy(screener_class):
    if not self_check():
        log_event("strategy_close", "Strategy self_check() failed — skipping.")
        return StrategyResult(skipped=True)

    start_time = utc_now()
    signals = analyze_closing_signals(start_time, screener_class)
    if not signals:
        return StrategyResult(skipped=True)
    trades = monitor_closing_trades(signals, start_time)
    return StrategyResult(trades=trades, skipped=False)
