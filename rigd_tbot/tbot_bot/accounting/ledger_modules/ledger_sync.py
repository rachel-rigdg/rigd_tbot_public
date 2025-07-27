# tbot_bot/accounting/ledger_modules/ledger_sync.py

from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
from tbot_bot.accounting.ledger_modules.ledger_snapshot import snapshot_ledger_before_sync
from tbot_bot.accounting.ledger_modules.ledger_double_entry import validate_double_entry, post_double_entry
from tbot_bot.accounting.coa_mapping_table import load_mapping_table
from tbot_bot.accounting.reconciliation_log import log_reconciliation_entry
from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS
import sqlite3
import json

PRIMARY_FIELDS = ("symbol", "datetime_utc", "action", "price", "quantity", "total_value")

def _sanitize_entry(entry):
    sanitized = {}
    for k, v in entry.items():
        if isinstance(v, (dict, list)):
            sanitized[k] = json.dumps(v)
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

def sync_broker_ledger():
    bot_identity = get_identity_tuple()
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity
    snapshot_ledger_before_sync()
    mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)
    trades_raw = fetch_all_trades(start_date="2025-01-01", end_date=None)
    cash_acts_raw = fetch_cash_activity(start_date="2025-01-01", end_date=None)

    print("TRADES RAW:", trades_raw)
    print("CASH_ACTS RAW:", cash_acts_raw)

    trades = []
    for t in trades_raw:
        if not isinstance(t, dict):
            print("NON-DICT TRADE DETECTED:", type(t), t)
            continue
        normalized = normalize_trade(t)
        if normalized.get("skip_insert", False):
            print("SKIP INVALID TRADE ACTION:", normalized.get("json_metadata", {}).get("unmapped_action", "unknown"), "| RAW:", t)
            continue
        # --- FIX: Ensure group_id is always set ---
        if not normalized.get("group_id"):
            normalized["group_id"] = normalized.get("trade_id")
        # --- SKIP blank/empty trades ---
        if _is_blank_entry(normalized):
            print("SKIP BLANK TRADE ENTRY:", normalized)
            continue
        trades.append(normalized)

    cash_acts = []
    for c in cash_acts_raw:
        if not isinstance(c, dict):
            print("NON-DICT CASH ACTIVITY DETECTED:", type(c), c)
            continue
        normalized = normalize_trade(c)
        if normalized.get("skip_insert", False):
            print("SKIP INVALID CASH ACTION:", normalized.get("json_metadata", {}).get("unmapped_action", "unknown"), "| RAW:", c)
            continue
        # --- FIX: Ensure group_id is always set for cash activity as well ---
        if not normalized.get("group_id"):
            normalized["group_id"] = normalized.get("trade_id")
        # --- SKIP blank/empty cash entries ---
        if _is_blank_entry(normalized):
            print("SKIP BLANK CASH ENTRY:", normalized)
            continue
        cash_acts.append(normalized)

    all_entries = [e for e in (trades + cash_acts) if isinstance(e, dict)]

    def _fill_defaults(entry):
        for k in TRADES_FIELDS:
            if k not in entry or entry[k] is None:
                entry[k] = None
        return entry

    seen = set()
    deduped_entries = []
    for e in all_entries:
        tid = e.get("trade_id")
        side = e.get("side")
        key = (tid, side)
        if tid and side and key in seen:
            continue
        seen.add(key)
        deduped_entries.append(e)

    all_entries = [_fill_defaults(e) for e in deduped_entries]

    sanitized_entries = [_sanitize_entry(e) for e in all_entries]
    post_double_entry(sanitized_entries, mapping_table)
    validate_double_entry()
    sync_run_id = f"sync_{entity_code}_{jurisdiction_code}_{broker_code}_{bot_id}_{sqlite3.datetime.datetime.utcnow().isoformat()}"
    for entry in all_entries:
        trade_id = entry.get("trade_id")
        jm = entry.get("json_metadata")
        if not isinstance(jm, dict):
            print("json_metadata is not a dict! type=", type(jm), "value=", jm)
            api_hash = ""
        else:
            api_hash = jm.get("api_hash", "")
        log_reconciliation_entry(
            trade_id=trade_id,
            status="matched",
            compare_fields={},
            sync_run_id=sync_run_id,
            api_hash=api_hash,
            broker=broker_code,
            raw_record=entry,
            mapping_version=str(mapping_table.get("version", "")),
            notes="Imported by sync",
            entity_code=entity_code,
            jurisdiction_code=jurisdiction_code,
            broker_code=broker_code
        )
