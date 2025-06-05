# tbot_bot/trading/risk_bot.py
# Risk management enforcement (allocations, max trades)
"""
Evaluates trade proposals against configured capital allocation, open position limits,
risk thresholds, blacklist logic, and strategy weightings before allowing entry.
All trades must be routed through this module before execution.
"""

from tbot_bot.config.env_bot import env_config
from tbot_bot.support.utils_log import log_event
from tbot_bot.enhancements.ticker_blocklist import is_ticker_blocked

# Load configuration from env_config (single-broker, no live/paper)
TOTAL_ALLOCATION = float(env_config.get("TOTAL_ALLOCATION", 0.02))
MAX_TRADES = int(env_config.get("MAX_TRADES", 4))
WEIGHTS = [float(w) for w in str(env_config.get("WEIGHTS", "0.4,0.2,0.2,0.2")).split(",")]
MAX_OPEN_POSITIONS = int(env_config.get("MAX_OPEN_POSITIONS", 5))
MAX_RISK_PER_TRADE = float(env_config.get("MAX_RISK_PER_TRADE", 0.025))


def get_trade_weight(index: int, active_count: int) -> float:
    """
    Returns the normalized weight for the trade signal at the given index.
    """
    if active_count <= 0:
        log_event("risk_bot", "Invalid active signal count: 0")
        return 0.0

    weights = WEIGHTS[:active_count]
    if len(weights) < active_count:
        # Fill missing weights equally if not enough weights defined
        remaining = active_count - len(weights)
        weights += [1.0 / active_count] * remaining
        log_event("risk_bot", f"Insufficient weights defined; padded with equal split for {remaining} signals")

    total_weight = sum(weights)
    if total_weight == 0:
        log_event("risk_bot", "Total weight is zero — defaulting to equal split")
        return 1.0 / active_count

    normalized_weight = weights[index] / total_weight
    return normalized_weight


def validate_trade(symbol: str, side: str, account_balance: float, open_positions_count: int, signal_index: int, total_signals: int):
    """
    Fully validates a proposed trade signal before execution.
    Includes position count limit, blacklist check, allocation logic, and per-trade risk cap.
    """
    if is_ticker_blocked(symbol):
        return False, f"{symbol} is on the blocklist"

    if open_positions_count >= MAX_OPEN_POSITIONS:
        return False, "Too many open positions"

    if signal_index >= MAX_TRADES:
        return False, "Max trades exceeded"

    weight = get_trade_weight(signal_index, total_signals)
    allocation = account_balance * TOTAL_ALLOCATION * weight
    max_risk = account_balance * MAX_RISK_PER_TRADE

    if allocation > max_risk:
        return False, f"Trade allocation ({allocation:.2f}) exceeds max risk ({max_risk:.2f})"

    return True, allocation
