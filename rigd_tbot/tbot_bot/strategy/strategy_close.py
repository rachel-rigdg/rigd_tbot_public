# tbot_bot/strategy/strategy_close.py
# summary: Implements Late-day momentum/fade strategy with VIX gating and bi-directional logic; compresses analysis/monitor window to 1min if TEST_MODE
# additions: pre-run bot_state gate, idempotent daily stamp, write start stamp on launch
# console: adds stdout prints for launch/debug visibility (flush=True)

import os  # (surgical) allow TBOT_STRATEGY_FORCE override
from datetime import timedelta, datetime, timezone
from pathlib import Path
import importlib

from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now, now_local
from tbot_bot.support.utils_log import log_event
from tbot_bot.trading.utils_etf import get_inverse_etf
from tbot_bot.trading.utils_puts import get_put_option
from tbot_bot.trading.utils_shorts import get_short_instrument
from tbot_bot.trading.orders_bot import create_order
from tbot_bot.strategy.strategy_meta import StrategyResult
from tbot_bot.enhancements.vix_gatekeeper import is_vix_above_threshold
from tbot_bot.trading.risk_module import validate_trade
from tbot_bot.config.error_handler_bot import handle as handle_error
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.support import path_resolver  # ensure control path consistency
# --- NEW (surgical): centralized trailing-stop helper ---
from tbot_bot.trading.trailing_stop import compute_trailing_exit_threshold, should_exit_by_trailing  # noqa: F401

print("[strategy_close] module loaded", flush=True)

config = get_bot_config()
broker_creds = decrypt_json("broker_credentials")
BROKER_CODE = broker_creds.get("BROKER_CODE", "").lower()

STRAT_CLOSE_ENABLED   = config["STRAT_CLOSE_ENABLED"]
CLOSE_ANALYSIS_TIME   = int(config["CLOSE_ANALYSIS_TIME"])
CLOSE_MONITORING_TIME = int(config["CLOSE_MONITORING_TIME"])
VIX_THRESHOLD         = float(config["STRAT_CLOSE_VIX_THRESHOLD"])
SHORT_TYPE_CLOSE      = config["SHORT_TYPE_CLOSE"]
ACCOUNT_BALANCE       = float(config["ACCOUNT_BALANCE"])
MAX_RISK_PER_TRADE    = float(config["MAX_RISK_PER_TRADE"])
DEFAULT_CAPITAL_PER_TRADE = ACCOUNT_BALANCE * MAX_RISK_PER_TRADE
MAX_TRADES            = int(config["MAX_TRADES"])
CANDIDATE_MULTIPLIER  = int(config["CANDIDATE_MULTIPLIER"])
FRACTIONAL            = str(config.get("FRACTIONAL", "false")).lower() == "true"
WEIGHTS               = [float(w) for w in config["WEIGHTS"].split(",")]

# --- Control/stamps (use tbot_bot/control via resolver) ---
CONTROL_DIR        = path_resolver.get_project_root() / "tbot_bot" / "control"
BOT_STATE_PATH     = CONTROL_DIR / "bot_state.txt"
CLOSE_STAMP_PATH   = CONTROL_DIR / "last_strategy_close_utc.txt"
TEST_MODE_FLAG     = CONTROL_DIR / "test_mode.flag"

SESSION_LOGS = []

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

def self_check():
    return STRAT_CLOSE_ENABLED and VIX_THRESHOLD >= 0

def get_broker_api():
    broker_api = importlib.import_module("tbot_bot.broker.broker_api")
    return broker_api

# ------------------------
# Idempotency helpers
# ------------------------
def _read_iso_utc(path: Path):
    if not path.exists():
        return None
    try:
        txt = path.read_text(encoding="utf-8").strip()
        if txt.endswith("Z"):
            txt = txt.replace("Z", "+00:00")
        return datetime.fromisoformat(txt)
    except Exception:
        return None

def _write_iso_utc(path: Path, when_dt: datetime):
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = when_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(ts, encoding="utf-8")

def _has_close_run_today(now_dt: datetime) -> bool:
    ts = _read_iso_utc(CLOSE_STAMP_PATH)
    return bool(ts and ts.date() == now_dt.date())
# ------------------------

def analyze_closing_signals(start_time, screener_class):
    log_event("strategy_close", "Starting EOD momentum/fade analysis...")
    analysis_minutes = 1 if is_test_mode_active() else CLOSE_ANALYSIS_TIME
    deadline = start_time + timedelta(minutes=analysis_minutes)
    print(f"[strategy_close] analyze_closing_signals start; deadline={deadline.isoformat()}", flush=True)
    signals = []

    if not is_vix_above_threshold(VIX_THRESHOLD) and not is_test_mode_active():
        log_event("strategy_close", "VIX filter blocked strategy.")
        print("[strategy_close] VIX gate blocked strategy (not test mode) — exiting analysis.", flush=True)
        return signals

    screener = screener_class(strategy="close")
    broker_api = get_broker_api()
    candidate_status = []
    # Use local time for window
    while now_local() < deadline:
        try:
            # Use screener-provided candidates only; no internal price/volume/mcap filtering here
            screener_data = screener.run_screen(pool_size=MAX_TRADES * CANDIDATE_MULTIPLIER)
        except Exception as e:
            handle_error("strategy_close", "LogicError", e)
            screener_data = []

        if not screener_data:
            log_event("strategy_close", "No symbols passed filter — none eligible for trading. Skipping to next cycle or idle.")
            print("[strategy_close] screener returned no symbols — exiting analysis.", flush=True)
            return []

        allocations = []
        for i in range(MAX_TRADES):
            alloc = ACCOUNT_BALANCE * (WEIGHTS[i] if i < len(WEIGHTS) else MAX_RISK_PER_TRADE)
            allocations.append(alloc)

        eligible_signals = []
        for idx, stock in enumerate(screener_data):
            if len(eligible_signals) >= MAX_TRADES:
                break
            symbol = stock["symbol"]
            price = float(stock["price"])
            # Strategy-specific signal logic (not eligibility filtering):
            # prefer late-day momentum near highs; fade if deep below intraday midpoint.
            high = float(stock.get("high", 0))
            low = float(stock.get("low", 0))
            range_mid = (high + low) / 2 if (high > 0 and low > 0) else 0

            if high > 0 and price > high * 0.995:
                direction = "buy"
            elif range_mid > 0 and price < range_mid * 0.9:
                direction = "sell"
            else:
                candidate_status.append({
                    "symbol": symbol,
                    "rank": idx + 1,
                    "fractional": None,
                    "min_order_size": None,
                    "alloc": None,
                    "status": "rejected",
                    "reason": "No valid EOD momentum/fade signal",
                    "price": price
                })
                continue

            alloc = allocations[len(eligible_signals)]
            is_fractional = broker_api.supports_fractional(symbol)
            min_order_size = broker_api.get_min_order_size(symbol)
            reason = None
            if FRACTIONAL and not is_fractional:
                reason = "Fractional shares not supported"
            elif alloc < min_order_size:
                reason = f"Order size {alloc} below minimum {min_order_size}"

            status_entry = {
                "symbol": symbol,
                "rank": idx + 1,
                "fractional": is_fractional,
                "min_order_size": min_order_size,
                "alloc": alloc,
                "status": "eligible" if not reason else "rejected",
                "reason": reason or "",
                "price": price
            }
            candidate_status.append(status_entry)
            if reason:
                log_event("strategy_close", f"REJECT: {symbol} - {reason}")
                continue

            eligible_signals.append({
                "symbol": symbol,
                "price": price,
                "side": direction,
                "high": high,
                "low": low,
                "alloc": alloc
            })

        SESSION_LOGS.clear()
        SESSION_LOGS.extend(candidate_status)
        log_event("strategy_close", f"EOD eligible signals: {eligible_signals}")
        print(f"[strategy_close] eligible_signals={len(eligible_signals)}", flush=True)
        return eligible_signals
    return []

def monitor_closing_trades(signals, start_time):
    log_event("strategy_close", "Monitoring EOD trades...")
    trades = []
    monitoring_minutes = 1 if is_test_mode_active() else CLOSE_MONITORING_TIME
    deadline = start_time + timedelta(minutes=monitoring_minutes)
    print(f"[strategy_close] monitor_closing_trades start; deadline={deadline.isoformat()}", flush=True)

    for signal in signals:
        if now_local() >= deadline:
            break

        symbol = signal["symbol"]
        side = signal["side"]
        price = signal["price"]
        alloc = signal["alloc"]

        try:
            if side == "buy":
                valid, alloc_amt = validate_trade(symbol, "buy", ACCOUNT_BALANCE, 0, 0, 1)
                if valid:
                    result = create_order(
                        symbol=symbol,
                        side="buy",
                        capital=alloc_amt,
                        price=price,
                        # --- CHANGED (surgical): broker-native trailing if available; else runtime-managed ---
                        stop_loss_pct=0.02,
                        strategy="close",
                        use_trailing_stop=True,
                    )
                    if result:
                        trades.append(result)
            elif side == "sell":
                if SHORT_TYPE_CLOSE == "disabled":
                    log_event("strategy_close", f"Short skipped for {symbol} (SHORT_TYPE disabled)")
                else:
                    valid, alloc_amt = validate_trade(symbol, "sell", ACCOUNT_BALANCE, 0, 0, 1)
                    if valid:
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
                            symbol=instrument,
                            side=side_exec,
                            capital=alloc_amt,
                            price=price,
                            # --- CHANGED (surgical): standardized trailing spec like other strategies ---
                            stop_loss_pct=0.02,
                            strategy="close",
                            use_trailing_stop=True,
                        )
                        if result:
                            trades.append(result)
        except Exception as e:
            handle_error("strategy_close", "BrokerError", e)

    log_event("strategy_close", f"Trades completed: {len(trades)}")
    return trades

def run_close_strategy(screener_class):
    print("[strategy_close] run_close_strategy() called", flush=True)
    # (surgical) Relaxed pre-run gate to match supervisor states and allow override
    try:
        state = (BOT_STATE_PATH.read_text(encoding="utf-8").strip() if BOT_STATE_PATH.exists() else "")
    except Exception:
        state = ""
    print(f"[strategy_close] bot_state='{state}'", flush=True)

    # --- SURGICAL CHANGE: include broader allowed states + env override ---
    allowed_states = {"running", "trading", "monitoring", "analyzing"}
    force = os.environ.get("TBOT_STRATEGY_FORCE", "0") == "1"
    if (state not in allowed_states) and not force:
        print("[strategy_close] exiting: bot_state not in {'running','trading','monitoring','analyzing'} (set TBOT_STRATEGY_FORCE=1 to override)", flush=True)
        log_event("strategy_close", f"Pre-run check: bot_state='{state}' — not runnable; exiting.")
        return StrategyResult(skipped=True)

    # Idempotency: if already launched today, exit quietly
    now = utc_now()
    if _has_close_run_today(now) and not force:
        print("[strategy_close] exiting: already stamped for today (idempotent guard)", flush=True)
        log_event("strategy_close", "Detected existing daily stamp — strategy_close already launched today; exiting.")
        return StrategyResult(skipped=True)

    # Successful start: write daily stamp immediately (prevents duplicate concurrent launches)
    _write_iso_utc(CLOSE_STAMP_PATH, now)
    print(f"[strategy_close] launching (stamp written) @ {now.isoformat()}", flush=True)
    log_event("strategy_close", f"Launching strategy_close (stamp written {now.isoformat().replace('+00:00','Z')})")

    if not self_check():
        log_event("strategy_close", "Strategy self_check() failed — skipping.")
        print("[strategy_close] self_check failed — exiting", flush=True)
        return StrategyResult(skipped=True)

    # Use local time for window logic
    start_time = now_local()
    print(f"[strategy_close] starting with screener={getattr(screener_class, '__name__', screener_class)}", flush=True)
    signals = analyze_closing_signals(start_time, screener_class)
    if not signals:
        print("[strategy_close] no signals — exiting", flush=True)
        return StrategyResult(skipped=True)
    trades = monitor_closing_trades(signals, start_time)
    print(f"[strategy_close] completed with {len(trades)} trades", flush=True)
    return StrategyResult(trades=trades, skipped=False)

def simulate_close(*args, **kwargs):
    """
    Stub for backtest/CI/test: returns empty list.
    """
    return []
