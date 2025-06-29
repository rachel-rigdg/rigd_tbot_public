# tbot_bot/strategy/strategy_mid.py
# summary: Implements VWAP-based mid-day reversal strategy with full bi-directional logic and env-driven parameters; compresses analysis/monitor window to 1min if TEST_MODE

from datetime import timedelta
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.trading.utils_etf import get_inverse_etf
from tbot_bot.trading.utils_puts import get_put_option
from tbot_bot.trading.utils_shorts import get_short_instrument
from tbot_bot.trading.orders_bot import create_order
from tbot_bot.strategy.strategy_meta import StrategyResult
from tbot_bot.enhancements.adx_filter import adx_filter
from tbot_bot.enhancements.bollinger_confluence import confirm_bollinger_touch
from tbot_bot.trading.kill_switch import trigger_shutdown
from tbot_bot.trading.risk_bot import validate_trade
from tbot_bot.config.error_handler_bot import handle as handle_error
from tbot_bot.support.decrypt_secrets import decrypt_json
from pathlib import Path

config = get_bot_config()
broker_creds = decrypt_json("broker_credentials")
BROKER_CODE = broker_creds.get("BROKER_CODE", "").lower()

STRAT_MID_ENABLED = config["STRAT_MID_ENABLED"]
MID_ANALYSIS_TIME = int(config["MID_ANALYSIS_TIME"])
MID_MONITORING_TIME = int(config["MID_MONITORING_TIME"])
VWAP_THRESHOLD = float(config["STRAT_MID_VWAP_THRESHOLD"])
SHORT_TYPE_MID = config["SHORT_TYPE_MID"]
ACCOUNT_BALANCE = float(config["ACCOUNT_BALANCE"])
MAX_RISK_PER_TRADE = float(config["MAX_RISK_PER_TRADE"])
DEFAULT_CAPITAL_PER_TRADE = ACCOUNT_BALANCE * MAX_RISK_PER_TRADE

CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

def self_check():
    return STRAT_MID_ENABLED and VWAP_THRESHOLD > 0

def analyze_vwap_signals(start_time, screener_class):
    log_event("strategy_mid", "Starting VWAP deviation analysis...")
    signals = []
    analysis_minutes = 1 if is_test_mode_active() else MID_ANALYSIS_TIME
    deadline = start_time + timedelta(minutes=analysis_minutes)
    screener = screener_class(strategy="mid")
    while utc_now() < deadline:
        try:
            screener_data = screener.run_screen(limit=50)
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

    log_event("strategy_mid", f"VWAP signals: {signals}")
    return signals

def execute_mid_trades(signals, start_time):
    log_event("strategy_mid", "Executing trades...")
    trades = []
    monitoring_minutes = 1 if is_test_mode_active() else MID_MONITORING_TIME
    deadline = start_time + timedelta(minutes=monitoring_minutes)

    for signal in signals:
        if utc_now() >= deadline:
            break

        side = signal["side"]
        symbol = signal["symbol"]
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
                        strategy_name="mid"
                    )
                    if result:
                        trades.append(result)
            else:
                if SHORT_TYPE_MID == "disabled":
                    log_event("strategy_mid", f"SHORT skipped for {symbol} (SHORT_TYPE disabled)")
                elif validate_trade(symbol, "sell", DEFAULT_CAPITAL_PER_TRADE):
                    instrument = None
                    side_exec = "sell"

                    if SHORT_TYPE_MID == "InverseETF":
                        instrument = get_inverse_etf(symbol)
                        if not instrument:
                            log_event("strategy_mid", f"No inverse ETF mapping for {symbol}, skipping short trade")
                            continue
                        side_exec = "buy"

                    elif SHORT_TYPE_MID == "LongPut":
                        instrument = get_put_option(symbol)
                        if not instrument:
                            log_event("strategy_mid", f"Put option contract unavailable for {symbol}, skipping short trade")
                            continue
                        side_exec = "buy"

                    elif SHORT_TYPE_MID in ("Short", "Synthetic"):
                        short_spec = get_short_instrument(symbol, BROKER_CODE, short_type=SHORT_TYPE_MID)
                        if not short_spec:
                            log_event("strategy_mid", f"No valid short method for {symbol} on {BROKER_CODE}")
                            continue
                        instrument = short_spec.get("symbol", symbol)
                        side_exec = short_spec.get("side", "sell")

                    else:
                        log_event("strategy_mid", f"Unsupported SHORT_TYPE_MID: {SHORT_TYPE_MID}")
                        continue

                    result = create_order(
                        ticker=instrument,
                        side=side_exec,
                        capital=DEFAULT_CAPITAL_PER_TRADE,
                        price=price,
                        stop_loss_pct=0.02,
                        strategy_name="mid"
                    )
                    if result:
                        trades.append(result)
        except Exception as e:
            handle_error("strategy_mid", "BrokerError", e)

    log_event("strategy_mid", f"Trades executed: {len(trades)}")
    return trades

def run_mid_strategy(screener_class):
    if not self_check():
        log_event("strategy_mid", "Strategy self_check() failed — skipping.")
        return StrategyResult(skipped=True)

    start_time = utc_now()
    signals = analyze_vwap_signals(start_time, screener_class)
    trades = execute_mid_trades(signals, start_time)
    return StrategyResult(trades=trades, skipped=False)
