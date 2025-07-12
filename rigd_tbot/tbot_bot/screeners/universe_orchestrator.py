# tbot_bot/screeners/universe_orchestrator.py
# Orchestrates the full nightly universe build process using YahooProvider directly.
# One-stage: fetch, filter, write unfiltered/partial/final via YahooProvider. Logs progress and errors.

import sys
from datetime import datetime
from tbot_bot.screeners.providers.yahoo_provider import YahooProvider

def log(msg):
    now = datetime.utcnow().isoformat() + "Z"
    print(f"[{now}] {msg}")

def main():
    try:
        log("Starting YahooProvider universe build...")
        provider = YahooProvider({"LOG_LEVEL": "verbose"})
        provider.full_universe_build()
        log("Universe orchestration completed successfully.")
    except Exception as e:
        log(f"Universe build failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
