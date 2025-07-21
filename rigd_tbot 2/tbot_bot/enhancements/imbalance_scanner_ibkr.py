# tbot_bot/enhancements/imbalance_scanner_ibkr.py
# Scans IBKR imbalance feed for market-on-close risk
# ------------------------------------------------------
# Monitors IBKR imbalance feed between 20:30–21:00 UTC for potential
# strong market-on-close pressure. Blocks trades if detected.

import datetime
from tbot_bot.support.utils_log import log_debug, log_error  # UPDATED

def get_current_utc():
    return datetime.datetime.utcnow()

def is_trade_blocked_by_imbalance(api_client):
    """
    Checks for strong order imbalance via IBKR market data feed.
    Only relevant during the close strategy window (typically 20:30–21:00 UTC).

    Args:
        api_client (IBKRBroker): Connected IBKR client supporting imbalance feed.

    Returns:
        bool: True if imbalance suggests trade should be blocked, else False.
    """
    now = get_current_utc()
    if now.hour != 20 or now.minute < 30 or now.minute > 59:
        return False  # Only activate during 20:30–21:00 UTC

    try:
        imbalances = api_client.get_market_imbalance_data()
        for imbalance in imbalances:
            side = imbalance.get("side")
            size = imbalance.get("size", 0)
            ticker = imbalance.get("ticker", "N/A")

            if side and size >= 500000:  # Arbitrary threshold: 500k shares
                log_debug(f"[imbalance_scanner_ibkr] Imbalance Detected: {ticker} [{side} {size}] — Trade Blocked")
                return True

        return False

    except Exception as e:
        log_error(f"[imbalance_scanner_ibkr] Failed to fetch imbalance data: {e}")
        return False  # Failsafe: allow trade if imbalance data not available
