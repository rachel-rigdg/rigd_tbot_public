# tbot_bot/trading/risk_module.py
# Risk management enforcement (allocations, max trades, enhancement pipeline)
"""
Evaluates trade proposals against configured capital allocation, open position limits,
risk thresholds, blacklist logic, enhancement modules, and strategy weightings before allowing entry.
All trades must be routed through this module before execution.
"""

from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_log import log_event
from datetime import datetime, timezone
print(f"[LAUNCH] risk_module.py launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)

# --- Enhancement imports (all core, fail-safe) ---
from tbot_bot.enhancements.ticker_blocklist import is_ticker_blocked

try:
    from tbot_bot.enhancements.adx_filter import get_adx
except ImportError:
    get_adx = None

try:
    from tbot_bot.enhancements.bollinger_confluence import get_bollinger_bands
except ImportError:
    get_bollinger_bands = None

try:
    from tbot_bot.enhancements.finnhub_fundamental_guard import passes_fundamental_guard
except ImportError:
    passes_fundamental_guard = None

try:
    from tbot_bot.enhancements.imbalance_scanner_ibkr import is_trade_blocked_by_imbalance
except ImportError:
    is_trade_blocked_by_imbalance = None

try:
    from tbot_bot.enhancements.vix_gatekeeper import get_vix_value
except ImportError:
    get_vix_value = None

try:
    from tbot_bot.enhancements.black_scholes_filter import validate_option
except ImportError:
    validate_option = None

config = get_bot_config()
TOTAL_ALLOCATION = float(config.get("TOTAL_ALLOCATION", 0.02))
MAX_TRADES = int(config.get("MAX_TRADES", 4))
WEIGHTS = [float(w) for w in str(config.get("WEIGHTS", "0.4,0.2,0.2,0.2")).split(",")]
MAX_OPEN_POSITIONS = int(config.get("MAX_OPEN_POSITIONS", 5))
MAX_RISK_PER_TRADE = float(config.get("MAX_RISK_PER_TRADE", 0.025))

ADX_MAX = float(config.get("ADX_MAX", 45))
VIX_MAX = float(config.get("VIX_MAX", 24))

def get_trade_weight(index: int, active_count: int) -> float:
    if active_count <= 0:
        log_event("risk_module", "Invalid active signal count: 0")
        return 0.0
    weights = WEIGHTS[:active_count]
    if len(weights) < active_count:
        remaining = active_count - len(weights)
        weights += [1.0 / active_count] * remaining
        log_event("risk_module", f"Insufficient weights defined; padded with equal split for {remaining} signals")
    total_weight = sum(weights)
    if total_weight == 0:
        log_event("risk_module", "Total weight is zero — defaulting to equal split")
        return 1.0 / active_count
    normalized_weight = weights[index] / total_weight
    return normalized_weight

def validate_trade(
    symbol: str,
    side: str,
    account_balance: float,
    open_positions_count: int,
    signal_index: int,
    total_signals: int,
    ibkr_client=None,
    option_data=None,
):
    """
    Fully validates a proposed trade signal before execution.
    Runs all enhancement modules, then core allocation and risk logic.
    Returns (True, allocation) if allowed; (False, reason) if blocked.
    """

    # 1. Enhancement: Blocklist
    if is_ticker_blocked(symbol):
        log_event("risk_module", f"{symbol} is on the blocklist")
        return False, f"{symbol} is on the blocklist"

    # 2. Enhancement: ADX Filter (trend too strong)
    if get_adx is not None:
        try:
            adx = get_adx(symbol)
            if adx is not None and adx > ADX_MAX:
                log_event("risk_module", f"ADX too high for {symbol}: {adx:.2f}")
                return False, f"ADX too high ({adx:.2f})"
        except Exception as e:
            log_event("risk_module", f"ADX check error: {e}")

    # 3. Enhancement: Bollinger Confluence
    if get_bollinger_bands is not None:
        try:
            bands = get_bollinger_bands(symbol)
            if bands:
                price = bands.get("price")
                lower = bands.get("lower")
                upper = bands.get("upper")
                if side == "long" and price is not None and lower is not None:
                    if price > lower:
                        log_event("risk_module", f"Bollinger block for {symbol} (long): price={price} > lower={lower}")
                        return False, "Bollinger band confluence block (long)"
                elif side == "short" and price is not None and upper is not None:
                    if price < upper:
                        log_event("risk_module", f"Bollinger block for {symbol} (short): price={price} < upper={upper}")
                        return False, "Bollinger band confluence block (short)"
        except Exception as e:
            log_event("risk_module", f"Bollinger check error: {e}")

    # 4. Enhancement: Finnhub Fundamentals
    if passes_fundamental_guard is not None:
        try:
            if not passes_fundamental_guard(symbol):
                log_event("risk_module", f"Fundamental block for {symbol}")
                return False, f"Fundamental block"
        except Exception as e:
            log_event("risk_module", f"Fundamental guard error: {e}")

    # 5. Enhancement: IBKR MOC Imbalance
    if is_trade_blocked_by_imbalance is not None and ibkr_client is not None:
        try:
            blocked = is_trade_blocked_by_imbalance(ibkr_client)
            if blocked:
                log_event("risk_module", f"MOC imbalance block for {symbol}")
                return False, f"IBKR imbalance block"
        except Exception as e:
            log_event("risk_module", f"IBKR imbalance check error: {e}")

    # 6. Enhancement: VIX Gatekeeper (spec: block when VIX >= VIX_MAX)
    if get_vix_value is not None:
        try:
            vix = get_vix_value()
            if vix is not None and vix >= VIX_MAX:
                log_event("risk_module", f"VIX too high: {vix:.2f}")
                return False, f"VIX above maximum ({vix:.2f})"
        except Exception as e:
            log_event("risk_module", f"VIX check error: {e}")

    # 7. Enhancement: Black-Scholes Filter (options only)
    if validate_option is not None and option_data is not None:
        try:
            ok, reason = validate_option(option_data)
            if not ok:
                log_event("risk_module", f"Black-Scholes block for {symbol}: {reason}")
                return False, f"Black-Scholes block: {reason}"
        except Exception as e:
            log_event("risk_module", f"Black-Scholes filter error: {e}")

    # --- Core risk/position/alloc checks ---
    if open_positions_count >= MAX_OPEN_POSITIONS:
        log_event("risk_module", "Too many open positions")
        return False, "Too many open positions"

    if signal_index >= MAX_TRADES:
        log_event("risk_module", "Max trades exceeded")
        return False, "Max trades exceeded"

    weight = get_trade_weight(signal_index, total_signals)
    allocation = account_balance * TOTAL_ALLOCATION * weight
    max_risk = account_balance * MAX_RISK_PER_TRADE

    if allocation > max_risk:
        log_event("risk_module", f"Trade allocation ({allocation:.2f}) exceeds max risk ({max_risk:.2f})")
        return False, f"Trade allocation ({allocation:.2f}) exceeds max risk ({max_risk:.2f})"

    return True, allocation
