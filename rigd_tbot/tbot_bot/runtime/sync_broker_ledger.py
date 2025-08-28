# tbot_bot/runtime/sync_broker_ledger.py
# Standalone script: synchronize broker ledger to internal system.
# Orchestrates pre-sync snapshot, invokes ledger_sync, and emits structured JSONL metrics.
# No direct DB I/O from this runtime wrapper.

import sys
import os
import json
from pathlib import Path
from datetime import datetime, timezone


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def main():
    # Add project root to sys.path for import reliability
    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import logging
    logging.basicConfig(level=logging.INFO)

    from tbot_bot.accounting.reconciliation_log import ensure_reconciliation_log_initialized
    from tbot_bot.accounting.ledger_modules.ledger_snapshot import snapshot_ledger_before_sync
    from tbot_bot.accounting.ledger_modules.ledger_sync import sync_broker_ledger
    from tbot_bot.support.utils_log import log_event  # writes JSONL
    from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple

    # Generate and propagate a sync_run_id through the pipeline (env-based propagation)
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    sync_run_id = f"sync_{entity_code}_{jurisdiction_code}_{broker_code}_{bot_id}_{_utc_now_iso()}"
    os.environ["TBOT_SYNC_RUN_ID"] = sync_run_id  # downstream may consume

    start_ts = _utc_now_iso()
    try:
        ensure_reconciliation_log_initialized()
        snapshot_ledger_before_sync()

        # Start event (structured)
        log_event(
            "sync_broker_ledger.start",
            {
                "sync_run_id": sync_run_id,
                "entity_code": entity_code,
                "jurisdiction_code": jurisdiction_code,
                "broker_code": broker_code,
                "bot_id": bot_id,
                "ts_utc": start_ts,
            },
            level="info",
        )

        # Invoke core sync. If it returns metrics, capture them; otherwise default.
        metrics = {
            "inserted_rows": None,
            "updated_rows": None,
            "skipped_unmapped": None,
            "opening_balance_posted": None,
        }
        try:
            maybe_metrics = sync_broker_ledger()  # may return a dict in newer builds
            if isinstance(maybe_metrics, dict):
                metrics.update({k: maybe_metrics.get(k) for k in metrics.keys()})
        except TypeError:
            # Older signature without return value
            sync_broker_ledger()

        end_ts = _utc_now_iso()
        log_event(
            "sync_broker_ledger.complete",
            {
                "sync_run_id": sync_run_id,
                "entity_code": entity_code,
                "jurisdiction_code": jurisdiction_code,
                "broker_code": broker_code,
                "bot_id": bot_id,
                "ts_utc": end_ts,
                "duration_sec": (datetime.fromisoformat(end_ts) - datetime.fromisoformat(start_ts)).total_seconds(),
                **metrics,
            },
            level="info",
        )
        # Concise completion line (human-friendly)
        log_event("sync_broker_ledger", f"sync completed @ {end_ts}")

        print(json.dumps({"ok": True, "sync_run_id": sync_run_id, **metrics}))
        sys.exit(0)

    except Exception as e:
        err_ts = _utc_now_iso()
        log_event(
            "sync_broker_ledger.error",
            {
                "sync_run_id": sync_run_id,
                "entity_code": entity_code,
                "jurisdiction_code": jurisdiction_code,
                "broker_code": broker_code,
                "bot_id": bot_id,
                "ts_utc": err_ts,
                "error": repr(e),
            },
            level="error",
        )
        print(json.dumps({"ok": False, "sync_run_id": sync_run_id, "error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
