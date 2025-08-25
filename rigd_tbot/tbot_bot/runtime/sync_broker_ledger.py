# tbot_bot/runtime/sync_broker_ledger.py
# Standalone script: synchronize broker ledger to internal system.
# Should be called by systemd, the web UI, or CLI automation.

import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main():
    # Add project root to sys.path for import reliability
    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    # Lazy imports from the app (no DB direct access here)
    try:
        from tbot_bot.accounting.reconciliation_log import ensure_reconciliation_log_initialized
    except Exception:
        # Fallback no-op if module path ever changes
        def ensure_reconciliation_log_initialized():
            return None  # pragma: no cover

    try:
        from tbot_bot.accounting.ledger_modules.ledger_sync import sync_broker_ledger
    except Exception as e:
        print(f"Unable to import sync orchestrator: {e}", file=sys.stderr)
        return 3

    # Structured logger (stdout for INFO, stderr for ERROR)
    logger = logging.getLogger("sync_broker_ledger")
    logger.setLevel(logging.INFO)
    h_out = logging.StreamHandler(sys.stdout)
    h_err = logging.StreamHandler(sys.stderr)
    h_out.setLevel(logging.INFO)
    h_err.setLevel(logging.ERROR)
    fmt = logging.Formatter("%(message)s")
    h_out.setFormatter(fmt)
    h_err.setFormatter(fmt)
    # Avoid duplicate handlers if called repeatedly
    logger.handlers = []
    logger.addHandler(h_out)
    logger.addHandler(h_err)

    # Optional structured app logger
    try:
        from tbot_bot.support.utils_log import log_event as _log_event  # type: ignore
    except Exception:
        def _log_event(message: str, level: str = "info", **fields):
            rec = {"ts_utc": _utc_now_iso(), "level": level, "message": message, **fields}
            line = json.dumps(rec, ensure_ascii=False)
            (logger.error if level.lower() == "error" else logger.info)(line)

    # CLI args
    parser = argparse.ArgumentParser(description="Synchronize broker ledger to internal system.")
    parser.add_argument("--start-date", dest="start_date", help="Inclusive start date (YYYY-MM-DD or ISO).", default=None)
    parser.add_argument("--end-date", dest="end_date", help="Inclusive end date (YYYY-MM-DD or ISO).", default=None)
    parser.add_argument("--json", dest="as_json", action="store_true", help="Print JSON summary to stdout.")
    args = parser.parse_args()

    # Initialize append-only reconciliation log table
    try:
        ensure_reconciliation_log_initialized()
    except Exception as e:
        _log_event("reconciliation_log_init_failed", level="error", error=str(e))

    # Kick off sync
    try:
        _log_event(
            "sync_broker_ledger_start",
            level="info",
            start_date=args.start_date,
            end_date=args.end_date,
        )
        summary = sync_broker_ledger(start_date=args.start_date, end_date=args.end_date)

        # Structured summary log
        _log_event("sync_broker_ledger_summary", level="info", **(summary or {}))

        if args.as_json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            # Human-friendly line plus compact JSON on the next line for logs
            status = (summary or {}).get("status", "unknown")
            counts = {
                k: summary.get(k, 0)
                for k in ("fetched", "normalized", "skipped_noise", "skipped_older", "backfill_overrides",
                          "rejected", "posted_groups", "inserted_rows", "dedup_skipped")
                if isinstance(summary.get(k, None), (int, float))
            }
            print(f"[ledger-sync] status={status} sync_run_id={summary.get('sync_run_id','')} counts={counts}")
            print(json.dumps(summary, ensure_ascii=False))

        # Exit codes:
        #   0 -> success (posted)
        #   2 -> completed but aborted/with rejects (no DB write or partial skip)
        code = 0 if (summary or {}).get("status") == "posted" else 2
        _log_event("sync_broker_ledger_end", level="info", exit_code=code)
        return code

    except SystemExit as se:
        # Propagate argparse or explicit exits cleanly
        return int(se.code) if isinstance(se.code, int) else 1
    except Exception as e:
        _log_event("sync_broker_ledger_failed", level="error", error=str(e))
        print(f"Broker ledger sync failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
