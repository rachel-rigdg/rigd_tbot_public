# tbot_bot/reporting/session_report.py
# Generates per-strategy/day summaries from the ledger (PnL, win rate, fees, counts)
# MUST ONLY BE LAUNCHED BY tbot_supervisor.py. Direct execution by CLI, main.py, or any other process is forbidden.

import sys

if __name__ == "__main__":
    print("[session_report.py] Direct execution is not permitted. This module must only be launched by tbot_supervisor.py.")
    sys.exit(1)

import csv
import os
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext
from collections import defaultdict

from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.path_resolver import get_output_path, resolve_ledger_db_path

# Prefer read-only query APIs; fall back to direct SQL if unavailable
try:
    from tbot_bot.accounting.ledger_modules.ledger_query import search_trades as _ledger_search_trades  # type: ignore
except Exception:  # pragma: no cover
    _ledger_search_trades = None  # fallback later

# ---- Legacy summary archive (preserved behavior; no deletions) ----
identity = get_bot_identity()  # {ENTITY}_{JURIS}_{BROKER}_{BOT_ID}
summary_filename = f"{identity}_BOT_daily_summary.json"
timestamped_filename = f"summary_{identity}_BOT_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"

SUMMARY_INPUT = get_output_path("summaries", summary_filename)
SUMMARY_ARCHIVE = get_output_path("summaries", timestamped_filename)


def _archive_legacy_summary():
    """Preserve legacy behavior: if a pre-built session summary exists, archive a timestamped copy."""
    os.makedirs(os.path.dirname(SUMMARY_ARCHIVE), exist_ok=True)
    if not os.path.exists(SUMMARY_INPUT):
        log_event("session_report", f"No legacy session summary found: {SUMMARY_INPUT}")
        return False
    try:
        with open(SUMMARY_INPUT, "r", encoding="utf-8") as f:
            data = json.load(f)
        with open(SUMMARY_ARCHIVE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        log_event("session_report", f"Legacy session summary archived to {SUMMARY_ARCHIVE}")
        return True
    except Exception as e:  # pragma: no cover
        log_event("session_report", f"Failed to archive legacy session summary: {e}")
        return False


# -------------------------
# New per-strategy/day report
# -------------------------

# Decimal policy
getcontext().prec = 28
TWOPL = Decimal("0.01")


def _dec(x) -> Decimal:
    try:
        return (Decimal(str(x)) if x is not None else Decimal("0")).quantize(TWOPL, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def _parse_utc(date_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        # Last resort: treat as current UTC
        return datetime.now(timezone.utc)


def _fetch_trades_window(start_utc_iso: str, end_utc_iso: str):
    """
    Returns list of dict rows from 'trades' view/table for [start,end], UTC.
    Prefers ledger_query; falls back to direct SQL.
    """
    rows = []
    if _ledger_search_trades:
        # Pull a large window via API and filter — keeps coupling minimal
        try:
            api_rows = _ledger_search_trades(sort_by="datetime_utc", sort_desc=False, limit=500000)  # type: ignore
            for r in api_rows:
                dt = r.get("datetime_utc") or r.get("timestamp_utc")
                if not dt:
                    continue
                if start_utc_iso <= dt <= end_utc_iso:
                    rows.append(r)
        except Exception:  # pragma: no cover
            rows = []
    if not rows:
        # Direct SQL fallback (read-only)
        try:
            ec, jc, bc, bid = identity.split("_")
            db_path = resolve_ledger_db_path(ec, jc, bc, bid)
            import sqlite3
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                # Use trades view if available; else fall back to raw trades table.
                # Columns used below: datetime_utc/timestamp_utc, group_id, strategy, account, total_value, side, commission, fee
                try:
                    sql = """
                      SELECT COALESCE(datetime_utc, timestamp_utc) AS dt,
                             COALESCE(group_id, trade_id) AS gid,
                             strategy, account, total_value, side, commission, fee
                        FROM trades
                       WHERE COALESCE(datetime_utc, timestamp_utc) >= ?
                         AND COALESCE(datetime_utc, timestamp_utc) <= ?
                       ORDER BY COALESCE(datetime_utc, timestamp_utc), id
                    """
                    rows = [dict(r) for r in conn.execute(sql, (start_utc_iso, end_utc_iso)).fetchall()]
                except Exception:
                    sql = """
                      SELECT datetime_utc AS dt,
                             COALESCE(group_id, trade_id) AS gid,
                             strategy, account, total_value, side, commission, fee
                        FROM trades
                       WHERE datetime_utc >= ? AND datetime_utc <= ?
                       ORDER BY datetime_utc, id
                    """
                    rows = [dict(r) for r in conn.execute(sql, (start_utc_iso, end_utc_iso)).fetchall()]
        except Exception as e:  # pragma: no cover
            log_event("session_report", f"Failed to read trades for report: {e}")
            rows = []
    return rows


def _aggregate(rows):
    """
    Aggregates per (UTC date, strategy):
      - counts: groups, wins, losses
      - win_rate
      - PnL_gross (income only), fees_total (commission+fee), PnL_net
    Definitions:
      income accounts: account LIKE 'Income:%' → credits (negative) => gross PnL = -sum(income)
      expense accounts: account LIKE 'Expenses:%' → debits (positive) => fees included in PnL_net
      group outcome uses net_pnl > 0 as win, < 0 as loss
    """
    # key: (YYYY-MM-DD, strategy)
    by_key = defaultdict(lambda: {
        "groups": 0,
        "wins": 0,
        "losses": 0,
        "gross_pnl": Decimal("0.00"),
        "fees_total": Decimal("0.00"),
        "net_pnl": Decimal("0.00"),
    })

    # accumulate per group to decide win/loss
    per_group = defaultdict(lambda: {
        "date": None,
        "strategy": "UNSPECIFIED",
        "income_sum": Decimal("0.00"),
        "expense_sum": Decimal("0.00"),
        "fees": Decimal("0.00"),
    })

    for r in rows:
        dt_iso = r.get("datetime_utc") or r.get("timestamp_utc") or r.get("dt")
        if not dt_iso:
            continue
        dt = _parse_utc(dt_iso)
        dkey = dt.strftime("%Y-%m-%d")
        gid = (r.get("group_id") or r.get("gid") or r.get("trade_id") or "").strip() or f"gid:{dkey}"
        strat = (r.get("strategy") or "UNSPECIFIED").strip() or "UNSPECIFIED"
        acct = (r.get("account") or "").strip()
        val = _dec(r.get("total_value"))
        fees = _dec(r.get("commission")) + _dec(r.get("fee"))

        g = per_group[gid]
        g["date"] = g["date"] or dkey
        g["strategy"] = g["strategy"] if g["strategy"] != "UNSPECIFIED" else strat
        g["fees"] += fees

        if acct.startswith("Income:"):
            g["income_sum"] += val  # typically negative
        elif acct.startswith("Expenses:"):
            g["expense_sum"] += val  # typically positive

    # roll up per group → per (date,strategy)
    for gid, g in per_group.items():
        date_key = g["date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        strat = g["strategy"] or "UNSPECIFIED"
        gross = (Decimal("0.00") - g["income_sum"])  # flip sign so profit is +
        fees_total = g["fees"]  # commissions+fees
        # Net PnL = gross - (explicit expenses + fees)
        net = gross - g["expense_sum"] - fees_total

        agg = by_key[(date_key, strat)]
        agg["groups"] += 1
        if net > 0:
            agg["wins"] += 1
        elif net < 0:
            agg["losses"] += 1
        agg["gross_pnl"] += gross
        agg["fees_total"] += fees_total
        agg["net_pnl"] += net

    # finalize metrics
    out = []
    for (date_key, strat), m in sorted(by_key.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        total = m["groups"]
        wins = m["wins"]
        losses = m["losses"]
        win_rate = (Decimal(wins) / Decimal(total) if total else Decimal("0")).quantize(Decimal("0.0001"))
        out.append({
            "session_date_utc": date_key,
            "strategy": strat,
            "groups": total,
            "wins": wins,
            "losses": losses,
            "win_rate": float(win_rate),
            "gross_pnl": float(m["gross_pnl"].quantize(TWOPL)),
            "fees_total": float(m["fees_total"].quantize(TWOPL)),
            "net_pnl": float(m["net_pnl"].quantize(TWOPL)),
        })
    return out


def generate_session_report(start_utc: str | None = None, end_utc: str | None = None) -> bool:
    """
    Build per-strategy/day summaries over [start_utc, end_utc] UTC (inclusive).
    If not provided, defaults to the current UTC day.
    Writes JSON + CSV artifacts to external reports directory (never re-ingested).
    """
    # Preserve legacy archive step (no deletions)
    _archive_legacy_summary()

    now = datetime.now(timezone.utc)
    if not start_utc:
        start_utc = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).isoformat()
    if not end_utc:
        end_utc = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=timezone.utc).isoformat()

    # Fetch & aggregate
    rows = _fetch_trades_window(start_utc, end_utc)
    summaries = _aggregate(rows)

    # Output paths (external artifacts only)
    base_ts = now.strftime("%Y%m%dT%H%M%SZ")
    json_name = f"{identity}_session_report_{base_ts}.json"
    csv_name = f"{identity}_session_report_{base_ts}.csv"
    json_path = get_output_path("reports", json_name)
    csv_path = get_output_path("reports", csv_name)
    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    payload = {
        "identity": identity,
        "window_utc": {"start": start_utc, "end": end_utc},
        "generated_at_utc": now.isoformat(),
        "rows": summaries,
        "meta": {"source": "ledger_query", "units": "base_currency", "version": "v048"},
    }

    try:
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(payload, jf, indent=2)

        # CSV flat table
        csv_cols = ["session_date_utc", "strategy", "groups", "wins", "losses", "win_rate", "gross_pnl", "fees_total", "net_pnl"]
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            writer = csv.DictWriter(cf, fieldnames=csv_cols)
            writer.writeheader()
            for r in summaries:
                writer.writerow(r)

        log_event("session_report", f"Session report written: {json_path} ; {csv_path}")
        return True
    except Exception as e:  # pragma: no cover
        log_event("session_report", f"Failed writing session report: {e}")
        return False
