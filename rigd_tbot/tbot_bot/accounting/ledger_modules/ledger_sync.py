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

def sync_broker_ledger():
    bot_identity = get_identity_tuple()
    entity_code, jurisdiction_code, broker_code, bot_id = bot_identity
    snapshot_ledger_before_sync()
    mapping_table = load_mapping_table(entity_code, jurisdiction_code, broker_code, bot_id)
    trades_raw = fetch_all_trades(start_date="2025-01-01", end_date=None)
    cash_acts_raw = fetch_cash_activity(start_date="2025-01-01", end_date=None)

    print("TRADES RAW:", trades_raw)
    print("CASH_ACTS RAW:", cash_acts_raw)

    # Filter for dict only, log and skip all non-dict
    trades = []
    for t in trades_raw:
        if not isinstance(t, dict):
            print("NON-DICT TRADE DETECTED:", type(t), t)
            continue
        trades.append(normalize_trade(t))

    cash_acts = []
    for c in cash_acts_raw:
        if not isinstance(c, dict):
            print("NON-DICT CASH ACTIVITY DETECTED:", type(c), c)
            continue
        cash_acts.append(normalize_trade(c))

    all_entries = [e for e in (trades + cash_acts) if isinstance(e, dict)]

    # Ensure all required/optional fields are present for full schema compliance
    def _fill_defaults(entry):
        for k in TRADES_FIELDS:
            if k not in entry:
                entry[k] = None
        return entry

    all_entries = [_fill_defaults(e) for e in all_entries]

    sanitized_entries = [_sanitize_entry(e) for e in all_entries]
    post_double_entry(sanitized_entries, mapping_table)
    validate_double_entry()
    sync_run_id = f"sync_{entity_code}_{jurisdiction_code}_{broker_code}_{bot_id}_{sqlite3.datetime.datetime.utcnow().isoformat()}"
    for entry in all_entries:
        trade_id = entry["trade_id"] if isinstance(entry, dict) and "trade_id" in entry else None
        jm = entry.get("json_metadata") if isinstance(entry, dict) else None
        if not isinstance(jm, dict):
            print("json_metadata is not a dict! type=", type(jm), "value=", jm)
            api_hash = ""
        else:
            api_hash = jm.get("api_hash", "")
        log_reconciliation_entry(
            trade_id=trade_id,
            status="ok",
            compare_fields={},
            sync_run_id=sync_run_id,
            api_hash=api_hash,
            broker=broker_code,
            raw_record=entry,
            mapping_version=str(mapping_table.get("version", "")),
            notes="Imported by sync"
        )
