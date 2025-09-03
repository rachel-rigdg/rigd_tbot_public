# tbot_bot/accounting/ledger_modules/ledger_sync.py

from tbot_bot.broker.broker_api import fetch_all_trades, fetch_cash_activity
# Try to import positions/cash snapshot helpers if available
try:
    from tbot_bot.broker.broker_api import fetch_positions, fetch_account  # preferred
except Exception:  # pragma: no cover
    fetch_positions = None
    fetch_account = None

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

import sqlite3
import json
from datetime import datetime, timezone, timedelta
from hashlib import sha256

# Path to ledger DB
from tbot_bot.support.path_resolver import resolve_ledger_db_path


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


# ----------------------------
# Local DB helpers (read-only + inserts for OB)
# ----------------------------
def _open_db():
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ledger_is_empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(1) AS c FROM trades").fetchone()
    return (row["c"] if row else 0) == 0


def _opening_already_posted(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM trades WHERE group_id LIKE 'OPENING_BALANCE_%' LIMIT 1"
    ).fetchone()
    return bool(row)


def _drop_in_columns(row: dict) -> dict:
    """
    Keep only columns that actually exist in TRADES_FIELDS to avoid SQL errors.
    """
    allowed = set(TRADES_FIELDS) | {"group_id", "sync_run_id"}
    return {k: row.get(k) for k in allowed}


def _insert_rows(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """
    Insert rows directly into trades (append-only) for Opening Balance only.
    Assumes each row includes required minimal columns present in TRADES_FIELDS.
    """
    if not rows:
        return
    cleaned = [_drop_in_columns(r) for r in rows]
    # Build a stable column set (intersection of all rows)
    cols = sorted(set().union(*(r.keys() for r in cleaned)))
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO trades ({', '.join(cols)}) VALUES ({placeholders})"
    vals = [tuple(r.get(c) for c in cols) for r in cleaned]
    conn.executemany(sql, vals)


# ----------------------------
# Broker snapshot (positions + cash)
# ----------------------------
def _safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _first_nonempty(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", {}):
            return v
    return default


def _get_broker_snapshot() -> dict:
    """
    Returns:
      {
        "positions": [ { "symbol": "...", "qty": float, "avg_cost": float, "market_value": float }, ... ],
        "cash": float|None
      }
    Tolerates different broker payload shapes.
    """
    positions_out = []
    cash_val = None

    # Positions
    try:
        raw_positions = fetch_positions() if callable(fetch_positions) else []
    except Exception:
        raw_positions = []
    for p in raw_positions or []:
        symbol = _first_nonempty(p, "symbol", "asset_symbol", "ticker", default="")
        qty = _safe_float(_first_nonempty(p, "qty", "quantity", "position_qty", default=0))
        avg_cost = _safe_float(_first_nonempty(p, "avg_entry_price", "avg_cost", "cost_basis_per_share", default=0))
        mval = _safe_float(_first_nonempty(p, "market_value", "market_val", default=qty * avg_cost))
        positions_out.append({"symbol": symbol, "qty": qty, "avg_cost": avg_cost, "market_value": mval})

    # Cash
    try:
        acct = fetch_account() if callable(fetch_account) else {}
    except Exception:
        acct = {}
    cash_val = _safe_float(
        _first_nonempty(
            acct or {}, "cash", "cash_balance", "portfolio_cash", "available_cash",
            default=None
        ),
        default=None,
    )

    return {"positions": positions_out, "cash": cash_val}


# ----------------------------
# Opening Balance posting
# ----------------------------
def _fitid(*parts: str) -> str:
    data = "|".join("" if p is None else str(p) for p in parts)
    return sha256(data.encode("utf-8")).hexdigest()


def _yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _build_ob_rows(
    *,
    entity_code: str,
    jurisdiction_code: str,
    broker_code: str,
    bot_id: str,
    snapshot: dict,
    dtposted: datetime,
    sync_run_id: str,
) -> list[dict]:
    """
    Build balanced double-entry splits for OB:
      - Positions:  debit  Brokerage:Equity:{SYMBOL}  +amount
                    credit Opening Balances:Equity     -amount
      - Cash:       debit  Brokerage:Cash              +cash
                    credit Opening Balances:Cash       -cash
    """
    rows: list[dict] = []
    ob_day = _yyyymmdd(dtposted)
    group_id = f"OPENING_BALANCE_{ob_day}"
    dt_iso = dtposted.astimezone(timezone.utc).isoformat()

    # Positions first
    for pos in snapshot.get("positions") or []:
        symbol = (pos.get("symbol") or "").strip()
        qty = _safe_float(pos.get("qty"), 0.0)
        # prefer cost basis; fall back to market value if no avg cost
        basis_per_share = _safe_float(pos.get("avg_cost"), 0.0)
        amount = qty * (basis_per_share if basis_per_share > 0 else _safe_float(pos.get("market_value"), 0.0) / (qty or 1.0))
        amount = round(amount, 2) if amount else 0.0
        if amount <= 0.0 or not symbol:
            continue

        # Debit: Brokerage:Equity:{SYMBOL}
        trade_id_deb = f"OB-{symbol}-{ob_day}-D"
        rows.append({
            "trade_id": trade_id_deb,
            "group_id": group_id,
            "sync_run_id": sync_run_id,
            "datetime_utc": dt_iso,
            "action": "OPENING_BALANCE",
            "symbol": symbol,
            "quantity": qty,
            "price": basis_per_share if basis_per_share > 0 else None,
            "total_value": amount,               # debit = +
            "side": "debit",
            "account": f"Brokerage:Equity:{symbol}",
            "notes": "Opening Balance (positions)",
            "json_metadata": json.dumps({
                "opening_balance": True,
                "source": "positions",
                "qty": qty,
                "avg_cost": basis_per_share,
                "market_value": _safe_float(pos.get("market_value"), None),
            }, ensure_ascii=False),
            "fitid": _fitid(broker_code, bot_id, "OB", "POS", symbol, ob_day, "D"),
        })

        # Credit: Opening Balances:Equity
        trade_id_cred = f"OB-{symbol}-{ob_day}-C"
        rows.append({
            "trade_id": trade_id_cred,
            "group_id": group_id,
            "sync_run_id": sync_run_id,
            "datetime_utc": dt_iso,
            "action": "OPENING_BALANCE",
            "symbol": symbol,
            "quantity": None,
            "price": None,
            "total_value": -amount,              # credit = -
            "side": "credit",
            "account": "Opening Balances:Equity",
            "notes": "Opening Balance offset",
            "json_metadata": json.dumps({
                "opening_balance": True,
                "source": "positions",
                "offset_for": trade_id_deb
            }, ensure_ascii=False),
            "fitid": _fitid(broker_code, bot_id, "OB", "POS", symbol, ob_day, "C"),
        })

    # Cash
    cash_amt = snapshot.get("cash", None)
    if cash_amt is not None:
        cash = round(_safe_float(cash_amt, 0.0), 2)
        if cash != 0.0:
            # Debit: Brokerage:Cash
            trade_id_deb = f"OB-CASH-{ob_day}-D"
            rows.append({
                "trade_id": trade_id_deb,
                "group_id": group_id,
                "sync_run_id": sync_run_id,
                "datetime_utc": dt_iso,
                "action": "OPENING_BALANCE",
                "symbol": "CASH",
                "quantity": None,
                "price": None,
                "total_value": cash,             # debit = +
                "side": "debit",
                "account": "Brokerage:Cash",
                "notes": "Opening Balance (cash)",
                "json_metadata": json.dumps({
                    "opening_balance": True,
                    "source": "account",
                }, ensure_ascii=False),
                "fitid": _fitid(broker_code, bot_id, "OB", "CASH", ob_day, "D"),
            })
            # Credit: Opening Balances:Cash
            trade_id_cred = f"OB-CASH-{ob_day}-C"
            rows.append({
                "trade_id": trade_id_cred,
                "group_id": group_id,
                "sync_run_id": sync_run_id,
                "datetime_utc": dt_iso,
                "action": "OPENING_BALANCE",
                "symbol": "CASH",
                "quantity": None,
                "price": None,
                "total_value": -cash,            # credit = -
                "side": "credit",
                "account": "Opening Balances:Cash",
                "notes": "Opening Balance offset",
                "json_metadata": json.dumps({
                    "opening_balance": True,
                    "source": "account",
                    "offset_for": trade_id_deb
                }, ensure_ascii=False),
                "fitid": _fitid(broker_code, bot_id, "OB", "CASH", ob_day, "C"),
            })

    return rows


def _post_opening_balances_if_needed(sync_run_id: str, earliest_trade_dt_utc: datetime | None) -> None:
    """
    Idempotent: insert OB group only if ledger empty AND no prior OB group present.
    DTPOSTED is set to just before earliest trade/cash activity (or now-1s if none).
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    with _open_db() as conn:
        if not _ledger_is_empty(conn):
            return
        if _opening_already_posted(conn):
            return

        # Fetch broker snapshot (positions + cash). If we have nothing, do not post OB.
        snapshot = _get_broker_snapshot()
        has_positions = bool(snapshot.get("positions"))
        has_cash = snapshot.get("cash") is not None and _safe_float(snapshot.get("cash")) != 0.0
        if not has_positions and not has_cash:
            return  # nothing to post

        # DTPOSTED: 1 second before earliest trade (if any) to keep OB at the very start
        dtposted = (earliest_trade_dt_utc - timedelta(seconds=1)) if earliest_trade_dt_utc else (datetime.now(timezone.utc) - timedelta(seconds=1))

        # Build rows and insert atomically
        rows = _build_ob_rows(
            entity_code=entity_code,
            jurisdiction_code=jurisdiction_code,
            broker_code=broker_code,
            bot_id=bot_id,
            snapshot=snapshot,
            dtposted=dtposted,
            sync_run_id=sync_run_id,
        )

        if not rows:
            return

        try:
            conn.execute("BEGIN")
            _insert_rows(conn, rows)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise


# ----------------------------
# Normalization helpers
# ----------------------------
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


# ----------------------------
# Main entrypoint
# ----------------------------
def sync_broker_ledger():
    """
    Fetch broker data, normalize, filter, dedupe, OB-on-first-sync, and write via double-entry posting.
    - OB posting is idempotent and executes ONLY when ledger is empty and no OB group exists.
    - OB uses broker positions + cash, grouped as OPENING_BALANCE_YYYYMMDD, DTPOSTED before earliest trade.
    - Then proceeds with normal ingest (mapping, posting, validation, reconciliation).
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    sync_run_id = f"sync_{entity_code}_{jurisdiction_code}_{broker_code}_{bot_id}_{datetime.now(timezone.utc).isoformat()}"

    # Snapshot before mutating the ledger
    snapshot_ledger_before_sync()

    # --- Pull raw broker activity FIRST so we can pick an earliest timestamp for OB anchoring ---
    trades_raw = fetch_all_trades(start_date="1970-01-01", end_date=None)
    cash_acts_raw = fetch_cash_activity(start_date="1970-01-01", end_date=None)

    # Determine earliest broker timestamp (UTC-ish strings handled later by normalizer)
    def _extract_dt_utc(record):
        # we rely on normalize_trade to convert; here try common fields quickly
        for key in ("datetime_utc", "timestamp", "time", "date"):
           
