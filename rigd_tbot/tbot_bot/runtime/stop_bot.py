# tbot_bot/runtime/stop_bot.py
# Safely exits all positions and ends session

"""
stop_bot.py – Gracefully exits all open positions and terminates active strategy sessions.
Triggered manually or via the API/web interface to ensure safe shutdown.
"""

from pathlib import Path
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.runtime.status_bot import bot_status
from tbot_bot.support.utils_time import utc_now              # UPDATED: from utils_time
from tbot_bot.support.utils_log import log_event         # UPDATED: from utils_log
from tbot_bot.reporting.summary_bot import generate_session_summary
from tbot_bot.broker.broker_api import get_active_broker  # Unified broker interface loader

def stop_bot_session():
    config = get_bot_config()

    # Load broker using unified adapter (no longer uses BROKER_CODE/_MODE logic)
    try:
        broker = get_active_broker()  # Handles adapter selection based on BROKER_NAME
    except Exception as e:
        log_event("stop_bot", f"Failed to initialize broker interface: {e}")
        bot_status.increment_error_count()
        return

    log_event("stop_bot", "Initiating bot shutdown sequence...")
    bot_status.set_state("shutdown")

    try:
        positions = broker.get_positions()
        for pos in positions:
            symbol = getattr(pos, "symbol", None) or pos.get("symbol")
            qty = getattr(pos, "position", None) or pos.get("qty") or pos.get("quantity")
            side = getattr(pos, "side", None) or pos.get("side") or pos.get("positionSide", "long")

            if not symbol or not qty:
                continue

            try:
                close_side = "sell" if str(side).lower() == "long" else "buy"
                broker.submit_order({
                    "symbol": symbol,
                    "qty": abs(float(qty)),
                    "side": close_side,
                    "order_type": "market",
                    "strategy": "shutdown",
                    "instrument_type": "equity"
                })
                log_event("stop_bot", f"Closed position: {symbol}, qty: {qty}, side: {close_side}")
            except Exception as e:
                log_event("stop_bot", f"Error closing position for {symbol}: {e}")
                bot_status.increment_error_count()
    except Exception as e:
        log_event("stop_bot", f"Failed to retrieve open positions: {e}")
        bot_status.increment_error_count()

    log_event("stop_bot", f"Shutdown complete at {utc_now().isoformat()}")
    bot_status.set_state("idle")

    # Write shutdown flag to control file
    CONTROL_DIR = config.get("CONTROL_DIR", "control")
    CONTROL_STOP_FILE = Path(CONTROL_DIR) / "control_stop.txt"
    CONTROL_STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTROL_STOP_FILE.write_text(f"STOPPED at {utc_now().isoformat()}")

    try:
        generate_session_summary()
    except Exception as e:
        log_event("stop_bot", f"Error generating session summary: {e}")

if __name__ == "__main__":
    stop_bot_session()
