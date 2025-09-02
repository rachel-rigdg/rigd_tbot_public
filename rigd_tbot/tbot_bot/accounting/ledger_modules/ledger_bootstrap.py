# tbot_bot/accounting/ledger_modules/ledger_bootstrap.py
# Opening balance bootstrap writer (append-only, double-entry, UTC, OFX-aligned).
# Inserts a single journal (group) of opening legs into the trades table and emits immutable audit records.

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from tbot_bot.support.path_resolver import (
    resolve_ledger_db_path,
    resolve_coa_json_path,
)
from tbot_bot.accounting.ledger_modules.ledger_audit import append as audit_append


@dataclass(frozen=True)
class OpeningLine:
    account_code: str
    amount: float
    note: Optional[str] = None


# ---------------------------
# COA helpers
# ---------------------------
def _active_coa_codes() -> Set[str]:
    """
    Load COA JSON and return set of ACTIVE account codes.
    Accepts either:
      - {"accounts":[...]}
      - list[...] (flat tree)
    """
    codes: Set[str] = set()
    try:
        p = resolve_coa_json_path()
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        def walk(nodes: List[Dict[str, Any]]) -> None:
            for n in nodes or []:
                code = str(n.get("code") or "").strip()
                active = bool(n.get("active", True))
                if code and active:
                    codes.add(code)
                kids = n.get("children") or []
                if isinstance(kids, list) and kids:
                    walk(kids)

        if isinstance(data, dict) and isinstance(data.get("accounts"), list):
            walk(data["accounts"])
        elif isinstance(data, list):
            walk(data)
    except Exception:
        # If COA can't be read, allow empty set; callers decide.
        pass
    return codes


# ---------------------------
# SQLite helpers
# ---------------------------
def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        return bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                (table,),
            ).fetchone()
        )
    except Exception:
        return False


def _columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _row_exists(conn: sqlite3.Connection, table: str, column: str, value: Any) -> bool:
    try:
        cur = conn.execute(f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (value,))
        return cur.fetchone() is not None
    except Exception:
        return False


# ---------------------------
# Core writer
# ---------------------------
def write_opening_entries(
    entity_code: str,
    jurisdiction_code: str,
    broker_code: str,
    bot_id: str,
    entries: List[Dict[str, Any]],
    actor: str,
) -> Dict[str, Any]:
    """
    Insert a single journal of opening-balance legs (append-only).

    Args:
      entity_code, jurisdiction_code, broker_code, bot_id: identity tuple for ledger routing.
      entries: list of dicts with keys:
          - account_code: str (COA code, must be active)
          - amount: float (signed; journal must sum exactly to 0.00)
          - note: optional str
          - datetime_utc: optional ISO8601 string (applies per-leg)
      actor: username or 'system' for audit attribution.

    Behavior:
      - Validates COA codes and double-entry (sum==0).
      - Groups all legs under a single group_id ("OB-{identity}-{YYYYMMDDTHHMMSSZ}").
      - Generates stable trade_ids ("OB-{identity}-{YYYYMMDD}-{seq}"), avoiding collisions.
      - Inserts rows into 'trades' with OFX-aligned fields (UTC).
      - Optionally inserts/updates 'trade_groups' row if the table exists.
      - Emits audit events: one group-level "opening_balance_seed" and per-leg "opening_balance_leg".

    Returns:
      {
        "group_id": str,
        "count": int,
        "sum": float,
        "trade_ids": List[str],
      }
    """
    if not entries or not isinstance(entries, list):
        raise ValueError("entries must be a non-empty list")

    # Normalize + validate lines
    lines: List[OpeningLine] = []
    total = 0.0
    active_codes = _active_coa_codes()
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("each entry must be a dict")
        acct = (raw.get("account_code") or raw.get("account") or "").strip()
        if not acct:
            raise ValueError("entry missing account_code")
        if active_codes and acct not in active_codes:
            raise ValueError(f"account_code '{acct}' is not active in COA")
        try:
            amt = float(raw.get("amount"))
        except Exception:
            raise ValueError(f"amount must be numeric for account '{acct}'")
        note = raw.get("note")
        lines.append(OpeningLine(account_code=acct, amount=amt, note=note))
        total += amt

    # Double-entry check (exact zero within 1e-6 tolerance)
    if not math.isclose(total, 0.0, abs_tol=1e-6):
        raise ValueError(f"opening journal not balanced (sum={total:.6f})")

    # Timestamps + ids
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    now_iso = now.isoformat().replace("+00:00", "Z")
    today = now.date().isoformat().replace("-", "")
    group_id = f"OB-{entity_code}{jurisdiction_code}{broker_code}{bot_id}-{now.strftime('%Y%m%dT%H%M%SZ')}"

    # Route ledger DB
    db_path = resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("BEGIN")

        trades_cols = _columns(conn, "trades")
        if "trades" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
            raise RuntimeError("trades table not found")

        # Ensure/insert trade_groups row if table exists
        if _table_exists(conn, "trade_groups"):
            tg_cols = _columns(conn, "trade_groups")
            tg_row = {
                "group_id": group_id,
                "description": "Opening Balance Journal",
                "status": "finalized",
                "tags": "opening_balance,bootstrap",
                "entity_code": entity_code,
                "jurisdiction_code": jurisdiction_code,
                "broker_code": broker_code,
                "created_by": actor or "system",
                "updated_by": actor or "system",
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            cols = [k for k in tg_row.keys() if k in tg_cols]
            placeholders = ",".join(["?"] * len(cols))
            conn.execute(
                f"INSERT OR IGNORE INTO trade_groups ({','.join(cols)}) VALUES ({placeholders})",
                tuple(tg_row[c] for c in cols),
            )

        # Insert legs
        trade_ids: List[str] = []
        seq = 1
        for idx, line in enumerate(lines, start=1):
            # Per-leg datetime override (optional)
            dt_raw = entries[idx - 1].get("datetime_utc")
            if isinstance(dt_raw, str) and dt_raw.strip():
                try:
                    # Normalize to Z
                    leg_dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
                    dt_iso = leg_dt.isoformat().replace("+00:00", "Z")
                except Exception:
                    dt_iso = now_iso
            else:
                dt_iso = now_iso

            # Generate unique trade_id
            base_id = f"OB-{entity_code}{jurisdiction_code}{broker_code}{bot_id}-{today}-{seq:03d}"
            t_id = base_id
            while _row_exists(conn, "trades", "trade_id", t_id):
                seq += 1
                t_id = f"OB-{entity_code}{jurisdiction_code}{broker_code}{bot_id}-{today}-{seq:03d}"

            # Build OFX-aligned row (only columns that exist are written)
            row = {
                "group_id": group_id,
                "datetime_utc": dt_iso,
                "symbol": None,
                "action": "OPENING_BALANCE",
                "quantity": None,
                "price": None,
                "fee": 0.0,
                "total_value": float(line.amount),
                "amount": float(line.amount),
                "account": line.account_code,
                "strategy": "bootstrap",
                "trade_id": t_id,
                "tags": "opening_balance,bootstrap",
                "notes": line.note or None,
                "entity_code": entity_code,
                "jurisdiction_code": jurisdiction_code,
                "broker_code": broker_code,
                "language": "en",
                "created_by": actor or "system",
                "updated_by": actor or "system",
                "approved_by": actor or "system",
                "approval_status": "approved",
                "gdpr_compliant": True,
                "ccpa_compliant": True,
                "pipeda_compliant": True,
                "hipaa_sensitive": False,
                "iso27001_tag": "",
                "soc2_type": "",
                "json_metadata": json.dumps(
                    {
                        "source": "ledger_bootstrap",
                        "seed": True,
                        "opening_balance": True,
                        "index": idx,
                    },
                    ensure_ascii=False,
                ),
                "raw_broker_json": json.dumps({}, ensure_ascii=False),
            }

            cols = [k for k in row.keys() if k in trades_cols]
            placeholders = ",".join(["?"] * len(cols))
            conn.execute(
                f"INSERT INTO trades ({','.join(cols)}) VALUES ({placeholders})",
                tuple(row[c] for c in cols),
            )
            trade_ids.append(t_id)

            # Per-leg audit (immutable)
            try:
                audit_append(
                    event="opening_balance_leg",
                    related_id=None,  # leg row id unknown without re-query; trade_id provided instead
                    actor=actor or "system",
                    group_id=group_id,
                    trade_id=t_id,
                    before=None,
                    after=line.account_code,
                    reason=line.note,
                    extra={
                        "amount": float(line.amount),
                        "datetime_utc": dt_iso,
                        "entity_code": entity_code,
                        "jurisdiction_code": jurisdiction_code,
                        "broker_code": broker_code,
                        "bot_id": bot_id,
                    },
                )
            except Exception:
                # Do not break the transaction if audit append fails; surface after commit if desired.
                pass

            seq += 1

        conn.commit()

        # Group-level audit
        try:
            audit_append(
                event="opening_balance_seed",
                related_id=None,
                actor=actor or "system",
                group_id=group_id,
                trade_id=None,
                before=None,
                after=None,
                reason="opening balance journal created",
                extra={
                    "count": len(lines),
                    "sum": round(total, 6),
                    "trade_ids": trade_ids,
                    "created_at_utc": now_iso,
                    "entity_code": entity_code,
                    "jurisdiction_code": jurisdiction_code,
                    "broker_code": broker_code,
                    "bot_id": bot_id,
                },
            )
        except Exception:
            # Non-fatal
            pass

        return {"group_id": group_id, "count": len(lines), "sum": round(total, 6), "trade_ids": trade_ids}

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
