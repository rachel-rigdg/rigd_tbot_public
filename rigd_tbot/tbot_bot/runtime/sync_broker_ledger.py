# tbot_bot/runtime/sync_broker_ledger.py
# Standalone script: synchronize broker ledger to internal system.
# Should be called by systemd, the web UI, or CLI automation.

import sys
from pathlib import Path

def main():
    # Add project root to sys.path for import reliability
    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import logging
    from tbot_bot.accounting.ledger import sync_broker_ledger
    from tbot_bot.support.utils_log import log_event

    try:
        logging.basicConfig(level=logging.INFO)
        log_event("sync_broker_ledger.py: Starting broker ledger sync")
        sync_broker_ledger()
        log_event("sync_broker_ledger.py: Broker ledger sync completed successfully")
        print("Broker ledger sync completed successfully.")
        sys.exit(0)
    except Exception as e:
        log_event(f"sync_broker_ledger.py: Broker ledger sync failed: {e}", level="error")
        print(f"Broker ledger sync failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
