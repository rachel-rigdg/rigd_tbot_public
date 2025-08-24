# tbot_bot/reporting/trade_logger.py
# append_trade(trade: dict) → writes OFX-aligned JSONL/CSV under /output/trades/ (external-only, NEVER re-ingest)
# MUST ONLY BE LAUNCHED BY tbot_supervisor.py. Direct execution by CLI, main.py, or any other process is forbidden.

import sys

if __name__ == "__main__":
    print("[trade_logger.py] Direct execution is not permitted. This module must only be launched by tbot_supervisor.py.")
    sys.exit(1)

import os
import json
import csv
from datetime import datetime, timezone
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path

# Load config (env-only)
config = get_bot_config()
BOT_IDENTITY = config.get("BOT_IDENTITY_STRING")
ENABLE_LOGGING = bool(config.get("ENABLE_LOGGING", True))

# Output artifacts (identity-scoped)
BASE_FILENAME = f"{BOT_IDENTITY}_BOT_trade_history"
JSONL_PATH = get_output_path("trades", f"{BASE_FILENAME}.json")   # JSON Lines (append-only)
CSV_PATH = get_output_path("trades", f"{BASE_FILENAME}.csv")      # CSV (append-only, fixed header)

# OFX-aligned export fields (superset; stable order)
CSV_FIELDS = [
    # OFX core
    "DTPOSTED",          # UTC ISO-8601
    "FITID",             # idempotency key
    "TRNTYPE",           # normalized action
    "TRNAMT",            # amount (signed)
    "CURRENCY",
    "NAME",              # short description (symbol)
    "MEMO",              # notes/description
    # Bot/ledger context
    "SYMBOL",
    "STRATEGY",
    "BROKER",
    "ACCOUNT",
    "SIDE",
    "GROUP_ID",
    "TRADE_ID",
    "RESPONSE_HASH",
    # Audit/meta
    "CREATED_AT_UTC",
    "UPDATED_AT_UTC",
    "BOT_IDENTITY",
    "NEVER_REINGEST",    # constant "TRUE" guard
]

def _utc_iso(dt_str: str | None) -> str:
    """
    Coerce any input time to tz-aware UTC ISO-8601 string.
    """
    if not dt_str:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()

def _map_trntype(action: str | None) -> str:
    """
    Map internal action → OFX TRNTYPE-ish label.
    """
    a = (action or "").lower()
    if a in ("buy", "long"): return "BUY"
    if a in ("sell", "short"): return "SELL"
    if a in ("dividend",): return "DIV"
    if a in ("interest",): return "INT"
    if a in ("fee", "commission"): return "FEE"
    if a in ("assignment",): return "ASSIGN"
    if a in ("exercise",): return "EXERCISE"
    if a in ("expire",): return "EXPIRE"
    if a in ("transfer",): return "XFER"
    if a in ("reorg",): return "REORG"
    return "OTHER"

def _ofx_row(trade: dict) -> dict:
    """
    Build OFX-aligned row from an internal trade dict.
    Required includes: FITID, STRATEGY, BROKER, RESPONSE_HASH, UTC timestamps.
    """
    fitid = trade.get("fitid") or trade.get("trade_id") or ""
    dtposted = _utc_iso(trade.get("datetime_utc") or trade.get("timestamp_utc"))
    created_utc = _utc_iso(trade.get("created_at_utc") or trade.get("created_at"))
    updated_utc = _utc_iso(trade.get("updated_at_utc") or trade.get("updated_at") or created_utc)

    # Monetary fields — prefer explicit 'amount' else 'total_value'
    amount = trade.get("amount")
    if amount is None:
        amount = trade.get("total_value")
    try:
        trnamt = float(amount if amount is not None else 0.0)
    except Exception:
        trnamt = 0.0

    row = {
        "DTPOSTED": dtposted,
        "FITID": str(fitid),
        "TRNTYPE": _map_trntype(trade.get("action")),
        "TRNAMT": trnamt,
        "CURRENCY": trade.get("currency_code") or trade.get("currency") or trade.get("price_currency") or "",
        "NAME": trade.get("symbol") or trade.get("description") or "",
        "MEMO": trade.get("notes") or trade.get("description") or "",
        "SYMBOL": trade.get("symbol") or "",
        "STRATEGY": trade.get("strategy") or "",
        "BROKER": trade.get("broker_code") or trade.get("broker") or "",
        "ACCOUNT": trade.get("account") or trade.get("account_code") or "",
        "SIDE": trade.get("side") or "",
        "GROUP_ID": trade.get("group_id") or trade.get("trade_id") or "",
        "TRADE_ID": trade.get("trade_id") or "",
        "RESPONSE_HASH": trade.get("response_hash") or trade.get("api_hash") or "",
        "CREATED_AT_UTC": created_utc,
        "UPDATED_AT_UTC": updated_utc,
        "BOT_IDENTITY": BOT_IDENTITY,
        "NEVER_REINGEST": "TRUE",
    }
    return row

def _ensure_outputs():
    """
    Ensure directory exists and write DO-NOT-REINGEST marker.
    """
    os.makedirs(os.path.dirname(JSONL_PATH), exist_ok=True)
    marker = os.path.join(os.path.dirname(JSONL_PATH), ".external_only.DO_NOT_REINGEST")
    try:
        if not os.path.exists(marker):
            with open(marker, "w", encoding="utf-8") as m:
                m.write("Artifacts in this directory are external audit exports and MUST NEVER be re-ingested.\n")
    except Exception:
        pass

def _append_jsonl(row: dict):
    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        json.dump(row, f, ensure_ascii=False)
        f.write("\n")

def _append_csv(row: dict):
    write_header = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})

def append_trade(trade: dict):
    """
    Append a single trade (dict) to JSONL and CSV audit logs (OFX-aligned).
    External-only artifacts; NEVER re-ingest.
    """
    if not ENABLE_LOGGING or not isinstance(trade, dict):
        return

    try:
        _ensure_outputs()
        row = _ofx_row(trade)
        _append_jsonl(row)  # JSON Lines
        _append_csv(row)    # CSV
        log_event("trade_logger", f"Appended trade to {JSONL_PATH} and {CSV_PATH}")
    except Exception as e:
        log_event("trade_logger", f"Failed to write trade: {e}", level="error")
