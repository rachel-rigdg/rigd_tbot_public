# tbot_bot/screeners/screener_core.py
# Core screener interface: symbol selection, enhancement/risk enforcement

from tbot_bot.screeners.symbol_universe_refresh import load_symbol_universe
from tbot_bot.enhancements.ticker_blocklist import is_ticker_blocked
from tbot_bot.trading.risk_module import validate_trade

def get_eligible_symbols(
    account_balance,
    open_positions_count,
    total_signals,
    side="buy"
):
    """
    Returns a list of eligible symbols for screening and trading,
    after universe/risk/blocklist checks.
    Args:
        account_balance (float): Current account value
        open_positions_count (int): Open positions currently held
        total_signals (int): Number of signals intended for allocation
        side (str): Trade direction ('buy'/'long' or 'sell'/'short')
    Returns:
        List[str]: List of eligible symbols
    """
    universe = load_symbol_universe()
    eligible = []
    for idx, symbol in enumerate(universe):
        if is_ticker_blocked(symbol):
            continue
        valid, _ = validate_trade(
            symbol=symbol,
            side=side,
            account_balance=account_balance,
            open_positions_count=open_positions_count,
            signal_index=idx,
            total_signals=total_signals
        )
        if valid:
            eligible.append(symbol)
    return eligible
