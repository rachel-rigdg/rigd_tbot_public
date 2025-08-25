# tbot_bot/accounting/ledger_modules/ledger_audit.py
"""
Append-only JSONL audit trail writer.
- Path resolution via path_resolver (derived from ledger DB path).
- Writes: before/after, actor, reason, audit_reference, group_id, ts_utc, fitid (+ core identity).
- Supports extras like sync_run_id, response_hash, api_hash, mapping_version.
- No deletes/rewrites; rotation is handled by immutable_log if available.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.utils_identity import get_bot_identity

# Optional rotation helper (no-op if missing)
try:
    from tbot_bot.accounting.ledger_modules import immutable_log as _ilog  # type: ignore
except Exception:  # pragma: no cover
    _ilog = None  # type: ignore

CONTROL_DIR = Path(__file__).resolve().parents[3] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_log_path() -> Path:
    """
    Resolve audit JSONL path relative to the resolved ledger DB path.
    """
    ec, jc, bc, bid = str(get_bot_identity()).split("_", 3)
    db_path = resolve_ledger_db_path(ec, jc, bc, bid)
    audit_dir = Path(db_path).parent / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    return audit_dir / "ledger_audit.jsonl"


def log_audit_event(
    action: str,
    entry_id: Optional[int],
    user: str,
    *,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    audit_reference: Optional[str] = None,
    group_id: Optional[str] = None,
    fitid: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append a single audit event as JSON line. Never mutates or deletes previous records.
    'extra' may include: sync_run_id, response_hash, api_hash, mapping_version, broker, table, etc.
    """
    if TEST_MODE_FLAG.exists():
        return

    ec, jc, bc, bid = str(get_bot_identity()).split("_", 3)
    record: Dict[str, Any] = {
        "ts_utc": _utc_now_iso(),
        "action": action,
        "entry_id": entry_id,
        "actor": user,
        "reason": reason,
        "audit_reference": audit_reference,
        "group_id": group_id,
        "fitid": fitid,
        "before": before,
        "after": after,
        "entity_code": ec,
        "jurisdiction_code": jc,
        "broker_code": bc,
        "bot_id": bid,
    }
    if extra:
        # Merge shallow extras without overwriting core keys
        for k, v in extra.items():
            record.setdefault(k, v)

    path = _audit_log_path()

    # Rotate if utility is available (size/time policies defined there)
    if _ilog and hasattr(_ilog, "rotate_if_needed"):
        try:
            _ilog.rotate_if_needed(path)  # type: ignore[attr-defined]
        except Exception:
            pass  # rotation is best-effort

    # Append-only JSONL write
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


__all__ = ["log_audit_event"]
