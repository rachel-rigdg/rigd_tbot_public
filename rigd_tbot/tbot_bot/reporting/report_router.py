# tbot_bot/reporting/report_router.py
# finalize_trade(trade: dict, strategy: str, mode: str) → routes to trade_logger, daily_summary, export_manager, email alert

from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.trading.logs_bot import log_trade
from tbot_bot.reporting.daily_summary import append_trade_to_summary
from tbot_bot.reporting.export_manager import export_trade_to_manager
from tbot_bot.trading.notifier_bot import notify_trade_fill
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event

# Load config once
config = get_bot_config()

# Optional toggles
NOTIFY_ON_FILL = config.get("NOTIFY_ON_FILL", False)
ENABLE_LOGGING = config.get("ENABLE_LOGGING", True)

def finalize_trade(trade: dict, strategy: str, mode: str):
    """
    Final handler for trade logging, accounting, notification, and summary.

    Args:
        trade (dict): Executed trade details.
        strategy (str): Strategy label ("open", "mid", "close").
        mode (str): "live" or "paper"
    """
    trade["timestamp"] = utc_now().isoformat()
    trade["strategy"] = strategy
    trade["mode"] = mode

    try:
        # 1. Log trade to JSON/CSV
        if ENABLE_LOGGING:
            log_trade(trade)

        # 2. Append to daily summary
        append_trade_to_summary(trade)

        # 3. Export to Manager.io-compatible accounting
        export_trade_to_manager(trade, mode=mode)

        # 4. Send notification
        if NOTIFY_ON_FILL:
            notify_trade_fill(
                ticker=trade.get("symbol"),
                side=trade.get("side"),
                size=trade.get("size"),
                price=trade.get("price"),
                strategy=strategy,
                broker=trade.get("broker", "unknown")
            )

        log_event("report_router", f"Finalized trade: {trade.get('symbol')} {trade.get('side')} x{trade.get('size')}")

    except Exception as e:
        log_event("report_router", f"Error finalizing trade: {e}", level="error")
