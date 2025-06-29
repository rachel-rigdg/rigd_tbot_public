# tbot_bot/screeners/universe_rebuild_cli.py
# CLI tool to manually trigger a universe cache rebuild (nightly process logic)
# Enforced: universe cache build uses ONLY /stock/symbol, /stock/profile2, /quote endpoints (per strict spec)
# Skips rebuild if cache was built within the last 22 hours, using get_cache_build_time and utc_now for rate limiting.

import sys
from tbot_bot.screeners.symbol_universe_refresh import main as rebuild_main
from tbot_bot.screeners.screener_utils import get_cache_build_time, utc_now

def main():
    build_time = get_cache_build_time()
    if build_time and (utc_now() - build_time).total_seconds() < 22 * 3600:
        print("[universe_rebuild_cli] Universe already built in last 22 hours. Skipping rebuild.")
        sys.exit(0)
    print("[universe_rebuild_cli] Forcing universe cache rebuild now...")
    try:
        rebuild_main()
        print("[universe_rebuild_cli] Universe cache rebuild complete.")
    except Exception as e:
        print(f"[universe_rebuild_cli] Rebuild failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
