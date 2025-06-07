# tbot_bot/strategy/strategy_mid.py
# summary: Implements VWAP-based mid-day reversal strategy with full bi-directional logic and env-driven parameters

import time
from datetime import datetime, timedelta
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now                      # UPDATED: from utils_time
from tbot_bot.support.utils_log import log_event                 # UPDATED: from utils_log
from tbot_bot.support.utils_etf import get_inverse_etf               # UPDATED: from utils_etf
from tbot_bot.screeners.finnhub_screener import get_filtered_stocks
from tbot_bot.trading.orders_bot import create_order
from tbot_bot.strategy.strategy_meta import StrategyResult
from tbot_bot.enhancements.adx_filter import adx_filter
from tbot_bot.enhancements.bollinger_confluence import confirm_bollinger_touch
from tbot_bot.trading.kill_switch import trigger_shutdown
from tbot_bot.risk.risk_bot import validate_trade
from tbot_bot.reporting.error_handler import handle_error
from tbot_bot.trading.instruments import resolve_bearish_instrument

config = get_bot_config()

TEST_MODE = config["TEST_MODE"]
STRAT_MID_ENABLED = config["STRAT_MID_ENABLED"]
MID_ANALYSIS_TIME = int(config["MID_ANALYSIS_TIME"])
MID_MONITORING_TIME = int(config["MID_MONITORING_TIME"])
VWAP_THRESHOLD = float(config["STRAT_MID_VWAP_THRESHOLD"])
SHORT_TYPE_MID = config["SHORT_TYPE_MID"]
ACCOUNT_BALANCE = float(config["ACCOUNT_BALANCE"])
MAX_RISK_PER_TRADE = float(config["MAX_RISK_PER_TRADE"])
DEFAULT_CAPITAL_PER_TRADE = ACCOUNT_BALANCE * MAX_RISK_PER_TRADE
SLEEP_TIME_STR = config["SLEEP_TIME"]

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

def self_check():
    return STRAT_MID_ENABLED and VWAP_THRESHOLD > 0

def analyze_vwap_signals(start_time):
    log_event("strategy_mid", "Starting VWAP deviation analysis...")
    signals = []
    deadline = start_time + timedelta(minutes=MID_ANALYSIS_TIME)
    cutoff = utc_now() + timedelta(minutes=1) if TEST_MODE else deadline

    while utc_now() < cutoff:
        try:
            screener_data = get_filtered_stocks(limit=50)
        except Exception as e:
            handle_error("strategy_mid", "LogicError", e)
            break

        if not screener_data:
            log_event("strategy_mid", "No screener results found — triggering kill switch.")
            trigger_shutdown("No candidates returned from screener")
            return []

        for stock in screener_data:
            symbol = stock["symbol"]
            price = float(stock["price"])
            vwap = float(stock.get("vwap", price))
            deviation = (price - vwap) / vwap if vwap > 0 else 0.0

            if abs(deviation) >= VWAP_THRESHOLD:
                direction = "buy" if deviation < 0 else "sell"
                if not adx_filter(symbol):
                    continue
                if not confirm_bollinger_touch(symbol, direction=direction):
                    continue
                signals.append({
                    "symbol": symbol,
                    "price": price,
                    "vwap": round(vwap, 2),
                    "side": direction,
                    "deviation": round(deviation, 4)
                })

        time.sleep(SLEEP_TIME)

    log_event("strategy_mid", f"VWAP signals: {signals}")
    return signals

def execute_mid_trades(signals, start_time):
    log_event("strategy_mid", "Executing trades...")
    trades = []
    deadline = start_time + timedelta(minutes=MID_MONITORING_TIME)

    for signal in signals:
        if utc_now() >= deadline:
            break

        side = signal["side"]
        try:
            if side == "buy":
                if validate_trade(signal["symbol"], "buy", DEFAULT_CAPITAL_PER_TRADE):
                    result = create_order(
                        ticker=signal["symbol"],
                        side="buy",
                        capital=DEFAULT_CAPITAL_PER_TRADE,
                        price=signal["price"],
                        stop_loss_pct=0.02,
                        strategy_name="mid"
                    )
                    if result:
                        trades.append(result)
            else:
                if SHORT_TYPE_MID == "disabled":
                    log_event("strategy_mid", f"SHORT skipped for {signal['symbol']} (SHORT_TYPE disabled)")
                elif validate_trade(signal["symbol"], "sell", DEFAULT_CAPITAL_PER_TRADE):
                    if SHORT_TYPE_MID == "InverseETF":
                        instrument = get_inverse_etf(signal["symbol"])
                        if not instrument:
                            log_event("strategy_mid", f"No inverse ETF mapping for {signal['symbol']}, skipping short trade")
                            continue
                        side_exec = "buy"  # Inverse ETF is long position
                    else:
                        instrument = resolve_bearish_instrument(signal["symbol"], SHORT_TYPE_MID)
                        side_exec = "sell"

                    result = create_order(
                        ticker=instrument,
                        side=side_exec,
                        capital=DEFAULT_CAPITAL_PER_TRADE,
                        price=signal["price"],
                        stop_loss_pct=0.02,
                        strategy_name="mid"
                    )
                    if result:
                        trades.append(result)
        except Exception as e:
            handle_error("strategy_mid", "BrokerError", e)

        time.sleep(SLEEP_TIME)

    log_event("strategy_mid", f"Trades executed: {len(trades)}")
    return trades

def run_mid_strategy():
    if not self_check():
        log_event("strategy_mid", "Strategy self_check() failed — skipping.")
        return StrategyResult(skipped=True)

    start_time = utc_now()
    signals = analyze_vwap_signals(start_time)
    trades = execute_mid_trades(signals, start_time)
    return StrategyResult(trades=trades, skipped=False)
