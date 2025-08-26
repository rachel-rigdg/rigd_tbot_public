# tbot_bot/accounting/ledger_modules/ledger_sync.py

"""
Ledger sync orchestrator (v048)

- import → normalize → tail-aware filter → compliance → dedupe → post
- Idempotency enforced (FITID UNIQUE + composite guards)
- Validation gate: rejects audited; 'timestamp_too_old' is overridden for backfill if:
    • the ledger is empty, or
    • the entry is strictly newer than the current ledger tail timestamp
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------- BROKER API RESOLUTION (robust fallbacks) ----------
# Your deployment may expose different names; this resolver normalizes them.
import importlib

def _resolve_broker_fetchers():
    api = importlib.import_module("tbot_bot.broker.broker_api")
    def _pick(names: List[str]):
        for n in names:
            fn = getattr(api, n, None)
            if callable(fn):
                return fn
        return None

    trades_fn = _pick([
        "fetch_all_trades", "fetch_trades", "list_trades", "get_all_trades", "get_trades"
    ])
    cash_fn = _pick([
        "fetch_cash_activity", "list_cash_activity", "get_cash_activity", "cash_activity", "fetch_cash"
    ])
    # Optional positions (not strictly required for ledger posting)
    positions_fn = _pick([
        "fetch_positions", "list_positions", "get_positions"
    ])
    if trades_fn is None:
        raise ImportError("broker_api is missing a trades fetcher (tried: fetch_all_trades/fetch_trades/list_trades/get_*).")
    if cash_fn is None:
        # Some brokers return cash movements mixed with trades; degrade gracefully.
        def _empty_cash(**_kwargs):  # type: ignore[unused-ignore]
            return []
        cash_fn = _empty_cash
    return trades_fn, cash_fn, positions_fn

_FETCH_TRADES_FN, _FETCH_CASH_FN, _FETCH_POSITIONS_FN = _resolve_broker_fetchers()

def _call_with_dates(fn, start_date: Optional[str], end_date: Optional[str]):
    # Be liberal in what we accept: kw, positional, only start, or no args.
    try:
        return fn(start_date=start_date, end_date=end_date)
    except TypeError:
        try:
            return fn(start_date=start_date)
        except TypeError:
            try:
                return fn(start_date, end_date)
            except TypeError:
                try:
                    return fn(start_date)
                except TypeError:
                    return fn()

# --------------------------------------------------------------

from tbot_bot.broker.utils.ledger_normalizer import normalize_trade

from tbot_bot.accounting.ledger_modules.ledger_entry import build_normalized_entry
from tbot_bot.accounting.ledger_modules.ledger_double_entry import (
    validate_double_entry,
    post_ledger_entries_double_entry,
)
from tbot_bot.accounting.ledger_modules.ledger_snapshot import snapshot_ledger_before_sync
from tbot_bot.accounting.ledger_modules.ledger_core import get_identity_tuple, get_conn
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


def _to_utc_dt(iso_like: Optional[str]) -> Optional[datetime]:
    if not iso_like:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_like).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _latest_ledger_timestamp() -> Optional[datetime]:
    """
    Return the latest timestamp in trades using the standard COALESCE column set.
    None if table empty or missing.
    """
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(COALESCE(timestamp_utc, datetime_utc, created_at_utc)) FROM trades"
            ).fetchone()
            return _to_utc_dt(row[0]) if row and row[0] else None
    except Exception:
        # If trades doesn't exist yet, treat as empty ledger (backfill allowed)
        return None


def _normalize_record_from_normalized(norm: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canonical field completion (fitid, identity, UTC) from an already normalized broker record.
    """
    e = build_normalized_entry(norm)
    if not e.get("group_id") and e.get("trade_id"):
        e["group_id"] = e["trade_id"]
    return e


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


# Legacy test shim expected by some tests
def _sanitize_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return build_normalized_entry(entry)


# -----------------
# Public orchestrator
# -----------------

def sync_broker_ledger(start_date: str | None = None, end_date: str | None = None) -> Dict[str, Any]:
    """
    Orchestrate broker → ledger sync.
    Tail-aware behavior:
      • Determine the current ledger tail timestamp.
      • Only consider entries strictly newer than that timestamp.
      • If the ledger is empty, allow full backfill (ignore 'timestamp_too_old').
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    sync_run_id = f"sync_{entity_code}_{jurisdiction_code}_{broker_code}_{bot_id}_{_utc_now_iso()}"

    # Point-in-time DB snapshot prior to mutation
    snapshot_ledger_before_sync()

    # Ensure DB-level UNIQUE guards (FITID + composite) BEFORE any inserts
    install_unique_guards()

    # Pull broker data (date filters are passed through if provided)
    trades_raw = _call_with_dates(_FETCH_TRADES_FN, start_date, end_date)
    cash_raw = _call_with_dates(_FETCH_CASH_FN, start_date, end_date)
    # positions are optional/one-shot; ignore if not present in this flow
    # positions_raw = _call_with_dates(_FETCH_POSITIONS_FN, start_date, end_date) if _FETCH_POSITIONS_FN else []

    ledger_tail_dt = _latest_ledger_timestamp()

    normalized: List[Dict[str, Any]] = []
    skipped_noise = 0
    skipped_older = 0

    # Normalize once via broker normalizer, respect skip, then complete canonical fields
    for raw in list(trades_raw) + list(cash_raw):
        if not isinstance(raw, dict):
            continue

        norm = normalize_trade(raw) or {}
        if norm.get("skip_insert"):
            skipped_noise += 1
            log_audit_event(
                action="sync_skip",
                entry_id=None,
                user="system",
                before={"raw": raw},
                after=None,
                reason=(norm.get("json_metadata") or {}).get("unmapped_action", "skip_insert"),
                audit_reference=sync_run_id,
                group_id=None,
                fitid=None,
                extra={"phase": "normalize"},
            )
            continue

        e = _normalize_record_from_normalized(norm)
        # Tail-aware filter: only accept entries strictly newer than ledger tail
        ts_dt = _to_utc_dt(e.get("timestamp_utc"))
        if ledger_tail_dt is not None and ts_dt is not None and ts_dt <= ledger_tail_dt:
            skipped_older += 1
            _recon_log(e, status="rejected", notes="older_than_ledger_tail", sync_run_id=sync_run_id)
            continue

        normalized.append(e)

    # Validation gate (pre-write compliance)
    rejects = 0
    backfill_overrides = 0
    valid_entries: List[Dict[str, Any]] = []
    for e in normalized:
        ok, errs = validate_entries([e])
        if ok:
            valid_entries.append(e)
            continue

        errs_list = list(errs or [])
        # Backfill override: if ONLY 'timestamp_too_old' blocks the entry, allow it when:
        #   • ledger is empty (tail None), or
        #   • entry is strictly newer than the current tail (we already enforced that above)
        if errs_list and set(errs_list) == {"timestamp_too_old"}:
            backfill_overrides += 1
            valid_entries.append(e)
            _recon_log(e, status="matched", notes="timestamp_too_old_overridden_by_tail_rule", sync_run_id=sync_run_id)
            log_audit_event(
                action="sync_backfill_override",
                entry_id=None,
                user="system",
                before=e,
                after=None,
                reason="timestamp_too_old_overridden_by_tail_rule",
                audit_reference=sync_run_id,
                group_id=e.get("group_id"),
                fitid=e.get("fitid"),
                extra={"phase": "validation"},
            )
            continue

        # Hard reject (other reasons)
        rejects += 1
        _recon_log(e, status="rejected", notes=";".join(errs_list or ["validation_failed"]), sync_run_id=sync_run_id)
        log_audit_event(
            action="sync_reject",
            entry_id=None,
            user="system",
            before=e,
            after=None,
            reason=";".join(errs_list or ["validation_failed"]),
            audit_reference=sync_run_id,
            group_id=e.get("group_id"),
            fitid=e.get("fitid"),
            extra={"phase": "validation"},
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
        "skipped_older": skipped_older,
        "backfill_overrides": backfill_overrides,
        "rejected": rejects,
        "posted_groups": 0,
        "inserted_rows": 0,
        "dedup_skipped": 0,
        "status": "aborted" if rejects > 0 else "posted",
        "ledger_tail_utc": ledger_tail_dt.isoformat() if ledger_tail_dt else None,
    }

    # Abort export/posting if any rejects detected
    if rejects > 0:
        return summary

    # In-memory dedupe (FITID→canonical key)
    deduped = deduplicate_entries(valid_entries)
    summary["dedup_skipped"] = len(valid_entries) - len(deduped)

    # Post (double-entry; atomic per group; idempotent at DB via UNIQUE guards)
    post_result = post_ledger_entries_double_entry(deduped)
    # Accept updated return shape (dict) or legacy list
    if isinstance(post_result, dict):
        inserted_ids = list(post_result.get("inserted_ids", []))
    else:
        inserted_ids = list(post_result or [])

    summary["inserted_rows"] = len(inserted_ids)
    # Count groups by group_id to be accurate
    try:
        summary["posted_groups"] = len({e.get("group_id") for e in deduped})
    except Exception:
        summary["posted_groups"] = len(deduped)

    # Double-entry integrity validation
    validate_double_entry()

    # Reconciliation: mark matched for all posted entries
    for e in deduped:
        _recon_log(e, status="matched", notes="Imported by sync", sync_run_id=sync_run_id)

    return summary
