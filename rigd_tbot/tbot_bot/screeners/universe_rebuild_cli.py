# tbot_bot/screeners/universe_rebuild_cli.py
# CLI tool to manually trigger a universe cache rebuild (nightly process logic)

import sys
from tbot_bot.screeners.symbol_universe_refresh import main as rebuild_main

def main():
    print("[universe_rebuild_cli] Forcing universe cache rebuild now...")
    try:
        rebuild_main()
        print("[universe_rebuild_cli] Universe cache rebuild complete.")
    except Exception as e:
        print(f"[universe_rebuild_cli] Rebuild failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
