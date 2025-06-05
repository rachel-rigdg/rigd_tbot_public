# tbot_bot/strategy/strategy_close.py
# summary: Implements Late-day momentum/fade strategy with VIX gating and bi-directional logic

import time
from datetime import timedelta
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.time_utils import utc_now                   # UPDATED: from time_utils
from tbot_bot.support.logging_utils import log_event              # UPDATED: from logging_utils
from tbot_bot.support.etf_utils import get_inverse_etf            # UPDATED: from etf_utils
from tbot_bot.screeners.finnhub_screener import get_filtered_stocks
from tbot_bot.trading.orders_bot import create_order
from tbot_bot.strategy.strategy_meta import StrategyResult
from tbot_bot.enhancements.vix_gatekeeper import is_vix_above_threshold
from tbot_bot.enhancements.imbalance_scanner_ibkr import is_trade_blocked_by_imbalance
from tbot_bot.enhancements.ticker_blocklist import is_ticker_blocked
from tbot_bot.trading.kill_switch import trigger_shutdown
from tbot_bot.risk.risk_bot import validate_trade
from tbot_bot.reporting.error_handler import handle_error
from tbot_bot.trading.instruments import resolve_bearish_instrument

config = get_bot_config()

TEST_MODE = config["TEST_MODE"]
STRAT_CLOSE_ENABLED = config["STRAT_CLOSE_ENABLED"]
CLOSE_ANALYSIS_TIME = int(config["CLOSE_ANALYSIS_TIME"])
CLOSE_MONITORING_TIME = int(config["CLOSE_MONITORING_TIME"])
VIX_THRESHOLD = float(config["STRAT_CLOSE_VIX_THRESHOLD"])
SHORT_TYPE_CLOSE = config["SHORT_TYPE_CLOSE"]
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
    return STRAT_CLOSE_ENABLED and VIX_THRESHOLD >= 0

def analyze_closing_signals(start_time):
    log_event("strategy_close", "Starting EOD momentum/fade analysis...")
    deadline = start_time + timedelta(minutes=CLOSE_ANALYSIS_TIME)
    cutoff = utc_now() + timedelta(minutes=1) if TEST_MODE else deadline
    signals = []

    if not is_vix_above_threshold(VIX_THRESHOLD):
        log_event("strategy_close", "VIX filter blocked strategy.")
        return signals

    while utc_now() < cutoff:
        try:
            screener_data = get_filtered_stocks(limit=50)
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
                "side": direction
            })

        time.sleep(SLEEP_TIME)

    log_event("strategy_close", f"EOD signals found: {len(signals)}")
    return signals

def monitor_closing_trades(signals, start_time):
    log_event("strategy_close", "Monitoring EOD trades...")
    trades = []
    deadline = start_time + timedelta(minutes=CLOSE_MONITORING_TIME)

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
                    if SHORT_TYPE_CLOSE == "InverseETF":
                        instrument = get_inverse_etf(symbol)
                        if not instrument:
                            log_event("strategy_close", f"No inverse ETF mapping for {symbol}, skipping short trade")
                            continue
                        side_exec = "buy"  # Inverse ETF is long position
                    else:
                        instrument = resolve_bearish_instrument(symbol, SHORT_TYPE_CLOSE)
                        side_exec = "sell"

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

def run_close_strategy():
    if not self_check():
        log_event("strategy_close", "Strategy self_check() failed — skipping.")
        return StrategyResult(skipped=True)

    start_time = utc_now()
    signals = analyze_closing_signals(start_time)
    if not signals:
        return StrategyResult(skipped=True)
    trades = monitor_closing_trades(signals, start_time)
    return StrategyResult(trades=trades, skipped=False)
