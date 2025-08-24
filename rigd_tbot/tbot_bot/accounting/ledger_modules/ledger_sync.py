# tbot_bot/accounting/ledger_modules/ledger_sync.py

"""
Ledger sync orchestrator (v048)

- import → normalize → compliance → dedupe → post
- Idempotency enforced (FITID UNIQUE + composite guards)
- Validation gate: rejects are audited & reconciled; posting aborts on rejects
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade

from tbot_bot.accounting.ledger_modules.ledger_entry import build_normalized_entry
from tbot_bot.accounting.ledger_modules.ledger_double_entry import (
    validate_double_entry,
    post_ledger_entries_double_entry,
)
from tbot_bot.accounting.ledger_modules.ledger_snapshot import snapshot_ledger_before_sync
from tbot_bot.accounting.ledger_modules.ledger_core import get_identity_tuple
from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import validate_entries
from tbot_bot.accounting.ledger_modules.ledger_deduplication import (
    deduplicate_entries,
    install_unique_guards,
)
from tbot_bot.accounting.ledger_modules.ledger_audit import log_audit_event

# Reconciliation log (support both locations)
try:
    from tbot_bot.accounting.ledger_modules.reconciliation_log import log_reconciliation_entry  # type: ignore
except Exception:  # pragma: no cover
    from tbot_bot.accounting.reconciliation_log import log_reconciliation_entry  # type: ignore


# -----------------
# Helpers
# -----------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Broker → bot normalization (via ledger_normalizer) + canonical completion.
    - Always goes through normalize_trade()
    - build_normalized_entry() fills identity, fitid, timestamp_utc, etc.
    """
    norm = normalize_trade(raw) or {}
    entry = build_normalized_entry(norm)
    # Ensure a stable default group_id
    if not entry.get("group_id") and entry.get("trade_id"):
        entry["group_id"] = entry["trade_id"]
    return entry


def _recon_log(entry: Dict[str, Any], *, status: str, notes: str, sync_run_id: str) -> None:
    try:
        log_reconciliation_entry(
            trade_id=entry.get("trade_id"),
            status=status,
            compare_fields={},
            sync_run_id=sync_run_id,
            api_hash=(entry.get("response_hash") or ""),
            broker=entry.get("broker_code"),
            raw_record=entry,
            mapping_version="",
            notes=notes,
            entity_code=entry.get("entity_code"),
            jurisdiction_code=entry.get("jurisdiction_code"),
            broker_code=entry.get("broker_code"),
        )
    except Exception:
        # Reconciliation logging must not break sync
        pass


# -----------------
# Public orchestrator
# -----------------

def sync_broker_ledger(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Orchestrate broker → ledger sync; returns a summary dict.
    Aborts posting if any entry fails validation (all rejects audited and recorded).
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    sync_run_id = f"sync_{entity_code}_{jurisdiction_code}_{broker_code}_{bot_id}_{_utc_now_iso()}"

    # Point-in-time DB snapshot prior to mutation
    snapshot_ledger_before_sync()

    # Ensure DB-level UNIQUE guards (adds fitid/timestamp_utc/created_at_utc and indexes) BEFORE inserts
    install_unique_guards()

    # Pull broker data (date filters are passed through if provided)
    trades_raw = fetch_all_trades(start_date=start_date, end_date=end_date)
    cash_raw = fetch_cash_activity(start_date=start_date, end_date=end_date)

    normalized: List[Dict[str, Any]] = []
    skipped_noise = 0

    # Normalize and drop "skip_insert" non-economic items early
    for raw in list(trades_raw) + list(cash_raw):
        if not isinstance(raw, dict):
            continue
        prelim = normalize_trade(raw) or {}
        if prelim.get("skip_insert"):
            skipped_noise += 1
            log_audit_event(
                action="sync_skip",
                entry_id=None,
                user="system",
                before={"raw": raw},
                after=None,
                reason=(prelim.get("json_metadata") or {}).get("unmapped_action", "skip_insert"),
                audit_reference=sync_run_id,
                group_id=None,
                fitid=None,
                extra={"phase": "normalize"},
            )
            continue
        normalized.append(_normalize_record(raw))

    # Validation gate (pre-write compliance, but lenient for backfills)
    rejects = 0
    valid_entries: List[Dict[str, Any]] = []
    IGNORABLE_ERRORS: Set[str] = {"timestamp_too_old"}  # accept backfills; still audit as warn

    for e in normalized:
        e_check = dict(e)
        # Allow Uncategorized here; mapping during double-entry will assign proper accounts
        e_check["allow_uncategorized"] = True
        ok, errs = validate_entries([e_check])

        if ok:
            valid_entries.append(e)
            continue

        errs_set = {er for er in (errs or []) if er}
        if errs_set and errs_set.issubset(IGNORABLE_ERRORS):
            # Accept but record warning (recon + audit)
            valid_entries.append(e)
            _recon_log(e, status="warn", notes="accepted_old_timestamp", sync_run_id=sync_run_id)
            log_audit_event(
                action="sync_warn",
                entry_id=None,
                user="system",
                before=e,
                after=None,
                reason="accepted_old_timestamp",
                audit_reference=sync_run_id,
                group_id=e.get("group_id"),
                fitid=e.get("fitid"),
                extra={"phase": "validation_pre_mapping"},
            )
            continue

        # Hard reject
        rejects += 1
        _recon_log(e, status="rejected", notes=";".join(errs or ["validation_failed"]), sync_run_id=sync_run_id)
        log_audit_event(
            action="sync_reject",
            entry_id=None,
            user="system",
            before=e,
            after=None,
            reason=";".join(errs or ["validation_failed"]),
            audit_reference=sync_run_id,
            group_id=e.get("group_id"),
            fitid=e.get("fitid"),
            extra={"phase": "validation_pre_mapping"},
        )

    summary: Dict[str, Any] = {
        "identity": {
            "entity_code": entity_code,
            "jurisdiction_code": jurisdiction_code,
            "broker_code": broker_code,
            "bot_id": bot_id,
        },
        "sync_run_id": sync_run_id,
        "fetched": len(trades_raw) + len(cash_raw),
        "normalized": len(normalized),
        "skipped_noise": skipped_noise,
        "rejected": rejects,
        "posted_groups": 0,
        "inserted_rows": 0,
        "dedup_skipped": 0,
        "status": "aborted" if rejects > 0 else "posted",
    }

    # Abort export/posting if any rejects detected
    if rejects > 0:
        return summary

    # In-memory dedupe (FITID→canonical/composite)
    deduped = deduplicate_entries(valid_entries)
    summary["dedup_skipped"] = len(valid_entries) - len(deduped)

    # Post (double-entry; atomic per group; idempotent via DB UNIQUE guards)
    post_result = post_ledger_entries_double_entry(deduped)

    # Accept updated return shape (dict) or legacy list
    if isinstance(post_result, dict):
        inserted_ids = list(post_result.get("inserted_ids", []))
    else:
        inserted_ids = list(post_result or [])

    summary["inserted_rows"] = len(inserted_ids)
    summary["posted_groups"] = len(deduped)

    # Double-entry integrity validation
    validate_double_entry()

    # Reconciliation: mark matched for all posted entries
    for e in deduped:
        _recon_log(e, status="matched", notes="Imported by sync", sync_run_id=sync_run_id)

    return summary


# -----------------
# Back-compat shim for older tests
# -----------------

def _sanitize_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Legacy helper expected by some tests; delegate to the canonical normalizer.
    """
    return build_normalized_entry(entry)
