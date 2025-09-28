# tbot_bot/strategy/strategy_open.py
# summary: Implements opening range breakout strategy with full bi-directional support and updated env references; compresses analysis/monitor window to 1min if TEST_MODE
# additions: pre-run bot_state gate, idempotent daily stamp, write start stamp on launch
# console: adds stdout prints for launch/debug visibility (flush=True)

import time
import os  # (surgical) for TBOT_STRATEGY_FORCE override
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
from tbot_bot.trading.risk_module import validate_trade
from tbot_bot.config.error_handler_bot import handle as handle_error
from tbot_bot.support.decrypt_secrets import decrypt_json
from tbot_bot.support import path_resolver  # ensure control path consistency
# (surgical) centralized bot-state writes
from tbot_bot.support.bot_state_manager import set_state

# NEW: central trailing-stop helper import (used for any runtime-managed trailing logic)
from tbot_bot.trading.trailing_stop import (
    compute_trailing_exit_threshold,
    should_exit_by_trailing,
    # --- SURGICAL: add helpers for per-strategy trail pct + pre-close tightening
    get_strategy_trail_pct,
    get_tightened_trailing_pct,
)

print("[strategy_open] module loaded", flush=True)

config = get_bot_config()
broker_creds = decrypt_json("broker_credentials")
BROKER_CODE = broker_creds.get("BROKER_CODE", "").lower()

STRAT_OPEN_ENABLED     = config["STRAT_OPEN_ENABLED"]
STRAT_OPEN_BUFFER      = float(config["STRAT_OPEN_BUFFER"])
OPEN_ANALYSIS_TIME     = int(config["OPEN_ANALYSIS_TIME"])
OPEN_BREAKOUT_TIME     = int(config["OPEN_BREAKOUT_TIME"])
OPEN_MONITORING_TIME   = int(config["OPEN_MONITORING_TIME"])
SHORT_TYPE_OPEN        = config["SHORT_TYPE_OPEN"]
ACCOUNT_BALANCE        = float(config["ACCOUNT_BALANCE"])
MAX_RISK_PER_TRADE     = float(config["MAX_RISK_PER_TRADE"])
DEFAULT_CAPITAL_PER_TRADE = ACCOUNT_BALANCE * MAX_RISK_PER_TRADE
MAX_TRADES             = int(config["MAX_TRADES"])
CANDIDATE_MULTIPLIER   = int(config["CANDIDATE_MULTIPLIER"])
FRACTIONAL             = str(config.get("FRACTIONAL", "false")).lower() == "true"
WEIGHTS                = [float(w) for w in config["WEIGHTS"].split(",")]
# SURGICAL: read trading trailing stop from env (defaults to 2%)
TRADING_TRAILING_STOP_PCT = float(config.get("TRADING_TRAILING_STOP_PCT", 0.02))
# SURGICAL: hard-close buffer (seconds) used by tightening helper (default ~2.5 min)
HARD_CLOSE_BUFFER_SEC = int(float(config.get("HARD_CLOSE_BUFFER_SEC", 150)))

# --- Control/stamps (ensure we use tbot_bot/control, not project root/control) ---
CONTROL_DIR     = path_resolver.get_project_root() / "tbot_bot" / "control"
BOT_STATE_PATH  = CONTROL_DIR / "bot_state.txt"
OPEN_STAMP_PATH = CONTROL_DIR / "last_strategy_open_utc.txt"
TEST_MODE_FLAG  = CONTROL_DIR / "test_mode.flag"

SESSION_LOGS = []
range_data = {}

def is_test_mode_active():
    return TEST_MODE_FLAG.exists()

def self_check():
    return STRAT_OPEN_ENABLED and STRAT_OPEN_BUFFER > 0

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

def _has_open_run_today(now_dt: datetime) -> bool:
    ts = _read_iso_utc(OPEN_STAMP_PATH)
    return bool(ts and ts.date() == now_dt.date())

# ------------------------

def analyze_opening_range(start_time, screener_class):
    log_event("strategy_open", "Starting opening range analysis...")
    # (surgical) state: entering analyze phase
    try:
        set_state("analyzing", reason="open:analyze")
    except Exception:
        pass
    analysis_minutes = 1 if is_test_mode_active() else OPEN_ANALYSIS_TIME
    deadline = start_time + timedelta(minutes=analysis_minutes)
    print(f"[strategy_open] analyze_opening_range start; deadline={deadline.isoformat()}", flush=True)
    screener = screener_class(strategy="open")
    global range_data
    range_data = {}
    # Use local time for window
    while now_local() < deadline:
        try:
            candidates = screener.run_screen(pool_size=MAX_TRADES * CANDIDATE_MULTIPLIER)
        except Exception as e:
            handle_error("strategy_open", "LogicError", e)
            break

        if not candidates:
            log_event("strategy_open", "No valid symbols returned — no trades will be placed this cycle.")
            return {}

        for stock in candidates:
            symbol = stock["symbol"]
            price = float(stock["price"])
            if symbol not in range_data:
                range_data[symbol] = {"high": price, "low": price}
            else:
                range_data[symbol]["high"] = max(range_data[symbol]["high"], price)
                range_data[symbol]["low"] = min(range_data[symbol]["low"], price)

    log_event("strategy_open", f"Range data collected for {len(range_data)} symbols.")
    return range_data

def detect_breakouts(start_time, screener_class):
    log_event("strategy_open", "Monitoring for breakouts...")
    trades = []
    breakout_minutes = 1 if is_test_mode_active() else OPEN_BREAKOUT_TIME
    deadline = start_time + timedelta(minutes=breakout_minutes)
    print(f"[strategy_open] detect_breakouts start; deadline={deadline.isoformat()}", flush=True)
    screener = screener_class(strategy="open")
    global range_data
    broker_api = get_broker_api()
    candidates_ranked = []
    candidate_status = []
    attempted_symbols = set()
    # Use local time for window
    try:
        candidates_ranked = screener.run_screen(pool_size=MAX_TRADES * CANDIDATE_MULTIPLIER)
    except Exception as e:
        handle_error("strategy_open", "LogicError", e)
        candidates_ranked = []

    # Precompute allocation per trade
    allocations = []
    for i in range(MAX_TRADES):
        alloc = ACCOUNT_BALANCE * (WEIGHTS[i] if i < len(WEIGHTS) else MAX_RISK_PER_TRADE)
        allocations.append(alloc)

    eligible_symbols = []
    rejected_candidates = []
    for idx, stock in enumerate(candidates_ranked):
        if len(eligible_symbols) >= MAX_TRADES:
            break
        symbol = stock["symbol"]
        price = float(stock["price"])
        # Eligibility checks
        is_fractional = broker_api.supports_fractional(symbol)
        min_order_size = broker_api.get_min_order_size(symbol)
        alloc = allocations[len(eligible_symbols)]
        reason = None

        if FRACTIONAL and not is_fractional:
            reason = "Fractional shares not supported"
        elif alloc < min_order_size:
            reason = f"Order size {alloc} below minimum {min_order_size}"
        elif symbol not in range_data:
            reason = "No range data"

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

        if not reason:
            eligible_symbols.append({"symbol": symbol, "price": price, "alloc": alloc})

    # Logging for UI/session
    SESSION_LOGS.clear()
    SESSION_LOGS.extend(candidate_status)

    # --- SURGICAL: compute effective (tightened) trailing % for 'open' strategy ---
    base_trail_pct = get_strategy_trail_pct("open", config, default_pct=TRADING_TRAILING_STOP_PCT)
    effective_trail_pct = get_tightened_trailing_pct(
        base_pct=base_trail_pct,
        now_utc=utc_now(),
        market_close_utc=str(config.get("MARKET_CLOSE_UTC", "20:00")),
        hard_close_buffer_s=HARD_CLOSE_BUFFER_SEC,
        tighten_factor=float(config.get("TRAIL_TIGHTEN_FACTOR", 0.5)),  # optional; defaults inside helper if missing
    )
    # DEBUG: log base vs effective to verify wiring at runtime
    log_event("strategy_open", f"Trailing stop pct (base → effective): {base_trail_pct:.6f} → {effective_trail_pct:.6f}")

    # (surgical) state: we are about to start submitting orders for eligible symbols
    try:
        set_state("trading", reason="open:placing")
    except Exception:
        pass

    # Only proceed with eligible
    for entry in eligible_symbols:
        symbol = entry["symbol"]
        price = entry["price"]
        alloc = entry["alloc"]
        high = range_data[symbol]["high"]
        low = range_data[symbol]["low"]
        long_trigger = high * (1 + STRAT_OPEN_BUFFER)
        short_trigger = low * (1 - STRAT_OPEN_BUFFER)

        # Long breakout
        if price > long_trigger:
            valid, alloc_amt = validate_trade(symbol, "buy", ACCOUNT_BALANCE, 0, 0, 1)
            if valid:
                try:
                    # NOTE: trailing-stop handled centrally; native if broker supports, else runtime can use helper
                    result = create_order(
                        symbol=symbol,
                        side="buy",
                        capital=alloc_amt,
                        price=price,
                        stop_loss_pct=effective_trail_pct,  # SURGICAL: tightened trailing %
                        strategy="open",
                        use_trailing_stop=True,
                    )
                    if result:
                        trades.append(result)
                        log_event("strategy_open", f"LONG breakout for {symbol} at {price}")
                except Exception as e:
                    handle_error("strategy_open", "BrokerError", e)
            range_data.pop(symbol, None)
            continue

        # Short breakout
        if price < short_trigger:
            if SHORT_TYPE_OPEN == "disabled":
                log_event("strategy_open", f"Short skipped for {symbol} (SHORT_TYPE disabled)")
            else:
                valid, alloc_amt = validate_trade(symbol, "sell", ACCOUNT_BALANCE, 0, 0, 1)
                if valid:
                    instrument = None
                    side = "sell"

                    if SHORT_TYPE_OPEN == "InverseETF":
                        instrument = get_inverse_etf(symbol)
                        if not instrument:
                            log_event("strategy_open", f"No inverse ETF mapping for {symbol}, skipping short trade")
                            continue
                        side = "buy"  # buy inverse ETF to synthetically short underlying

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
                        # NOTE: for inverse ETF (side='buy'), trailing helper semantics are short-like at the underlying,
                        # but orders_bot will apply correct directionality using the helper.
                        result = create_order(
                            symbol=instrument,
                            side=side,
                            capital=alloc_amt,
                            price=price,
                            stop_loss_pct=effective_trail_pct,  # SURGICAL: tightened trailing %
                            strategy="open",
                            use_trailing_stop=True,
                        )
                        if result:
                            trades.append(result)
                            log_event("strategy_open", f"SHORT breakout for {symbol} at {price} using {instrument}")
                    except Exception as e:
                        handle_error("strategy_open", "BrokerError", e)
            range_data.pop(symbol, None)

    # (surgical) state: enter monitoring after order placement phase concludes
    try:
        set_state("monitoring", reason="open:monitoring")
    except Exception:
        pass

    return trades

def run_open_strategy(screener_class):
    print("[strategy_open] run_open_strategy() called", flush=True)
    # (surgical) Relaxed pre-run gate: allow supervisor-driven states or env override
    try:
        state = (BOT_STATE_PATH.read_text(encoding="utf-8").strip() if BOT_STATE_PATH.exists() else "")
    except Exception:
        state = ""
    print(f"[strategy_open] bot_state='{state}'", flush=True)

    # --- SURGICAL CHANGE: include 'analyzing' in allowed states ---
    allowed_states = {"running", "trading", "monitoring", "analyzing"}
    force = os.environ.get("TBOT_STRATEGY_FORCE", "0") == "1"
    if (state not in allowed_states) and not force:
        print("[strategy_open] exiting: bot_state not in {'running','trading','monitoring','analyzing'} (set TBOT_STRATEGY_FORCE=1 to override)", flush=True)
        log_event("strategy_open", f"Pre-run check: bot_state='{state}' — not runnable; exiting.")
        return StrategyResult(skipped=True)

    # Idempotency: if already launched today, exit quietly
    now = utc_now()
    if _has_open_run_today(now) and not force:
        print("[strategy_open] exiting: already stamped for today (idempotent guard)", flush=True)
        log_event("strategy_open", "Detected existing daily stamp — strategy_open already launched today; exiting.")
        return StrategyResult(skipped=True)

    # Successful start: write daily stamp immediately (prevents duplicate concurrent launches)
    _write_iso_utc(OPEN_STAMP_PATH, now)
    print(f"[strategy_open] launching (stamp written) @ {now.isoformat()}", flush=True)
    log_event("strategy_open", f"Launching strategy_open (stamp written {now.isoformat().replace('+00:00','Z')})")

    if not self_check():
        log_event("strategy_open", "Strategy self_check() failed — skipping.")
        return StrategyResult(skipped=True)

    # Use local time for window logic
    start_time = now_local()
    print(f"[strategy_open] starting with screener={getattr(screener_class, '__name__', screener_class)}", flush=True)
    analyze_opening_range(start_time, screener_class)
    trades = detect_breakouts(start_time, screener_class)
    print(f"[strategy_open] completed with {len(trades)} trades", flush=True)
    log_event("strategy_open", f"Open strategy completed: {len(trades)} trades placed")
    return StrategyResult(trades=trades, skipped=False)

def simulate_open(*args, **kwargs):
    """Stub for backtest/CI/test: returns empty list (no simulated trades)."""
    return []
