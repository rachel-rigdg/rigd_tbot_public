from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
from tbot_bot.accounting.ledger_modules.ledger_snapshot import snapshot_ledger_before_sync
from tbot_bot.accounting.ledger_modules.ledger_double_entry import validate_double_entry, post_double_entry
from tbot_bot.accounting.coa_mapping_table import load_mapping_table
from tbot_bot.accounting.reconciliation_log import log_reconciliation_entry
from tbot_bot.accounting.ledger_modules.ledger_entry import get_identity_tuple
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade
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
    trades_raw = fetch_all_trades(start_date=None, end_date=None)
    cash_acts_raw = fetch_cash_activity(start_date=None, end_date=None)

    for t in trades_raw + cash_acts_raw:
        if not isinstance(t, dict):
            print("NON-DICT TRADE DETECTED:", type(t), t)

    trades = [normalize_trade(t) for t in trades_raw]
    cash_acts = [normalize_trade(c) for c in cash_acts_raw]
    all_entries = trades + cash_acts
    sanitized_entries = [_sanitize_entry(e) for e in all_entries]
    post_double_entry(sanitized_entries, mapping_table)
    validate_double_entry()
    sync_run_id = f"sync_{entity_code}_{jurisdiction_code}_{broker_code}_{bot_id}_{sqlite3.datetime.datetime.utcnow().isoformat()}"
    for entry in all_entries:
        log_reconciliation_entry(
            trade_id=entry.get("trade_id"),
            status="ok",
            compare_fields={},
            sync_run_id=sync_run_id,
            api_hash=entry.get("json_metadata", {}).get("api_hash", ""),
            broker=broker_code,
            raw_record=entry,
            mapping_version=str(mapping_table.get("version", "")),
            notes="Imported by sync"
        )
