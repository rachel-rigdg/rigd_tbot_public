# tbot_bot/runtime/start_bot.py
# Main entry point for bot; starts session lifecycle and strategy sequence

from dotenv import load_dotenv
from pathlib import Path

# Load .env from support/.env using absolute path resolution
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / "tbot_bot" / "support" / ".env")

import sys
import traceback
from tbot_bot.support.bootstrap_utils import is_first_bootstrap
from tbot_bot.config.env_bot import get_bot_config         # Loads and validates decrypted .env_bot
from tbot_bot.enhancements.build_check import run_build_check  # Verifies system readiness before trading
from tbot_bot.runtime.main import main                     # Core bot lifecycle handler
from tbot_bot.reporting.logs_bot import log_event          # Logs session events
from tbot_bot.config.error_handler_bot import handle as handle_error  # Centralized error classification
from tbot_bot.support.utils_time import utc_now            # UPDATED: Provides UTC timestamping

def start_bot():
    if is_first_bootstrap():
        print("[start_bot] System is in bootstrap phase. Configuration not complete. Startup aborted.")
        log_event("start_bot", "System is in bootstrap phase. Configuration not complete. Startup aborted.")
        sys.exit(0)

    config = get_bot_config()

    try:
        # Log start time of TradeBot execution
        log_event("start_bot", f"Starting TradeBot at {utc_now().isoformat()}")

        # Abort if DISABLE_ALL_TRADES is set to true
        if config.get("DISABLE_ALL_TRADES", False):
            log_event("start_bot", "DISABLE_ALL_TRADES is True. Startup aborted.")
            return

        # Validate all paths and config requirements before launching session
        run_build_check()

        # Run the full trading bot lifecycle
        main()

    except Exception as e:
        # Handle fatal startup errors and exit
        handle_error(e, strategy_name="start_bot", broker="n/a", category="ConfigError")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    start_bot()
