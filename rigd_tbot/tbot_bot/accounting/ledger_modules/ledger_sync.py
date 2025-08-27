# tbot_bot/accounting/ledger_modules/ledger_sync.py

from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
from tbot_bot.accounting.ledger_modules.ledger_snapshot import snapshot_ledger_before_sync
from tbot_bot.accounting.ledger_modules.ledger_double_entry import validate_double_entry, post_double_entry
from tbot_bot.accounting.coa_mapping_table import (
    load_mapping_table,
    get_mapping_for_transaction,
    flag_unmapped_transaction,
)
from tbot_bot.accounting.reconciliation_log import log_reconciliation_entry
from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
from tbot_bot.accounting.ledger_modules.ledger_opening_balance import post_opening_balances_if_needed

import sqlite3
import json
from datetime import datetime, timezone

# --- Compliance compatibility (supports old/new filter signatures) ---
try:
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import (
        is_compliant_ledger_entry as _is_compliant,  # boolean
    )
except Exception:
    from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import (
        compliance_filter_ledger_entry as _legacy_filter,  # entry-or-None OR (bool, reason)
    )

    def _is_compliant(entry: dict) -> bool:
        res = _legacy_filter(entry)
        if isinstance(res, tuple):
            return bool(res[0])
        return res is not None


PRIMARY_FIELDS = ("symbol", "datetime_utc", "action", "price", "quantity", "total_value")


def _sanitize_entry(entry):
    sanitized = {}
    for k, v in entry.items():
        if isinstance(v, (dict, list)):
            sanitized[k] = json.dumps(v, default=str)
        elif v is None:
            sanitized[k] = None
        else:
            sanitized[k] = v
    return sanitized


def _is_blank_entry(entry):
    # True if all primary display fields are None/empty
    return all(
        entry.get(f) is None or str(entry.get(f)).strip() == "" for f in PRIMARY_FIELDS
    )


def _ensure_group_id(entry: dict) -> dict:
    """Guarantee group_id exists; default to trade_id."""
    if not entry.get("group_id"):
        entry["group_id"] = entry.get("trade_id")
    return entry


def sync_broker_ledger():
    """
    Fetch broker data, normalize, filter, dedupe, and write via double-entry posting.
    - Ensures group_id is set (defaults to trade_id)
    - Skips blank / non-compliant / unmapped items (emits unmapped summary)
    - Tags all posted rows with sync_run_id
    - Calls Opening Balance post helper once on empty ledgers
    - Relies on atomic batch behavior of posting layer per Doc 050
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    sync_run_id = f"sync_{entity_code}_{jurisdiction_code}_{broker_code}_{bot_id}_{datetime.now(timezone.utc).isoformat()}"

    # Snapshot before mutating the ledger
    snapshot_ledger_before_sync()

    # Post opening balances if needed (detects empty ledger; no-op otherwise)
    try:
        broker_snapshot = {
            "as_of_utc": datetime.now(timezone.utc).isoformat(),
            # Optional hints if available from broker-specific layers (left minimal here):
            "cash": None,
            "positions": [],
        }
        post_opening_balances_if_needed(sync_run_id=sync_run_id, broker_snapshot=broker_snapshot)
    except Exception as e:
        # Non-fatal; continue normal ingest
        print("Opening balance helper error (continuing):", repr(e))

    # Mapping table for posting
    mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)

    # Pull from broker
    trades_raw = fetch_all_trades(start_date="2025-01-01", end_date=None)
    cash_acts_raw = fetch_cash_activity(start_date="2025-01-01", end_date=None)

    # Normalize + filter trades
    trades = []
    for t in trades_raw:
        if not isinstance(t, dict):
            print("NON-DICT TRADE DETECTED:", type(t), t)
            continue
        normalized = normalize_trade(t)
        if normalized.get("skip_insert", False):
            print(
                "SKIP INVALID TRADE ACTION:",
                (normalized.get("json_metadata") or {}).get("unmapped_action", "unknown"),
                "| RAW:",
                t,
            )
            continue
        _ensure_group_id(normalized)
        if _is_blank_entry(normalized):
            print("SKIP BLANK TRADE ENTRY:", normalized)
            continue
        if not _is_compliant(normalized):
            print("SKIP NON-COMPLIANT TRADE ENTRY:", normalized)
            continue
        trades.append(normalized)

    # Normalize + filter cash activities
    cash_acts = []
    for c in cash_acts_raw:
        if not isinstance(c, dict):
            print("NON-DICT CASH ACTIVITY DETECTED:", type(c), c)
            continue
        normalized = normalize_trade(c)
        if normalized.get("skip_insert", False):
            print(
                "SKIP INVALID CASH ACTION:",
                (normalized.get("json_metadata") or {}).get("unmapped_action", "unknown"),
                "| RAW:",
                c,
            )
            continue
        _ensure_group_id(normalized)
        if _is_blank_entry(normalized):
            print("SKIP BLANK CASH ENTRY:", normalized)
            continue
        if not _is_compliant(normalized):
            print("SKIP NON-COMPLIANT CASH ENTRY:", normalized)
            continue
        cash_acts.append(normalized)

    # Combine and dedupe raw normalized entries before posting
    # Use (trade_id, action, datetime_utc, total_value) as a stable key to avoid double-posting
    combined = trades + cash_acts
    seen = set()
    deduped_entries = []
    for e in combined:
        key = (
            e.get("trade_id"),
            e.get("action"),
            e.get("datetime_utc"),
            float(e.get("total_value") or 0.0),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_entries.append(e)

    # Tag all with sync_run_id and pad missing schema fields (defensive)
    def _fill_defaults(entry):
        for k in TRADES_FIELDS:
            if k not in entry:
                entry[k] = None
        entry["sync_run_id"] = sync_run_id
        return entry

    all_entries = [_fill_defaults(e) for e in deduped_entries]

    # Enforce skip-on-unmapped; emit unmapped summary into mapping table for UI
    mapped_entries = []
    unmapped = []
    for e in all_entries:
        m = get_mapping_for_transaction(e, mapping_table)
        if not m:
            unmapped.append(
                {
                    "trade_id": e.get("trade_id"),
                    "action": e.get("action"),
                    "datetime_utc": e.get("datetime_utc"),
                    "symbol": e.get("symbol"),
                    "notes": e.get("notes"),
                }
            )
            try:
                flag_unmapped_transaction(
                    {"broker": broker_code, "type": e.get("action"), "symbol": e.get("symbol"), "notes": e.get("notes")},
                    user="sync",
                )
            except Exception:
                pass
            continue
        mapped_entries.append(e)

    if unmapped:
        print(f"[SYNC] Unmapped entries skipped: {len(unmapped)} (details recorded for UI)")

    # Sanitize complex types -> JSON strings (safe for sqlite bindings downstream if needed)
    sanitized_entries = [_sanitize_entry(e) for e in mapped_entries]

    # Post using double-entry helper (handles account mapping, amount signs, and DB de-dup on (trade_id, side))
    post_double_entry(sanitized_entries, mapping_table)

    # Validate double-entry integrity
    validate_double_entry()

    # Write reconciliation records
    for entry in mapped_entries:
        trade_id = entry.get("trade_id")
        api_hash = ""
        jm = entry.get("json_metadata")
        if isinstance(jm, dict):
            api_hash = jm.get("api_hash", "") or jm.get("credential_hash", "")
        elif isinstance(jm, str):
            try:
                jm_obj = json.loads(jm)
                api_hash = jm_obj.get("api_hash", "") or jm_obj.get("credential_hash", "")
            except Exception:
                pass

        log_reconciliation_entry(
            trade_id=trade_id,
            status="matched",
            compare_fields={},
            sync_run_id=sync_run_id,
            api_hash=api_hash,
            broker=broker_code,
            raw_record=entry,
            mapping_version=str(load_mapping_table().get("version", "")),
            notes="Imported by sync",
            entity_code=entity_code,
            jurisdiction_code=jurisdiction_code,
            broker_code=broker_code,
        )
