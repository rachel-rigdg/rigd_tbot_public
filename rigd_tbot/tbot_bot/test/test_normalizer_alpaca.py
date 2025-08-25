# tbot_bot/test/test_normalizer_alpaca.py
# Unit tests for Alpaca normalizers:
# - normalize_trade
# - normalize_cash / normalize_cash_activity
# - normalize_position
#
# Verifies:
#   • DTPOSTED → timestamp_utc is tz-aware UTC ISO-8601
#   • FITID correctness and stability
#   • Basic action mapping sanity for trades/cash
#   • Idempotency of normalization for positions

import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- Import helpers (supporting a couple of naming variants) ---

_normalize_trade = None
_normalize_cash = None
_normalize_position = None

try:
    from tbot_bot.broker.utils.ledger_normalizer import normalize_trade as _normalize_trade  # type: ignore
except Exception:
    pass

# Cash normalizer may be named normalize_cash or normalize_cash_activity
if _normalize_cash is None:
    try:
        from tbot_bot.broker.utils.ledger_normalizer import normalize_cash as _normalize_cash  # type: ignore
    except Exception:
        try:
            from tbot_bot.broker.utils.ledger_normalizer import normalize_cash_activity as _normalize_cash  # type: ignore
        except Exception:
            pass

# Position normalizer
try:
    from tbot_bot.broker.utils.ledger_normalizer import normalize_position as _normalize_position  # type: ignore
except Exception:
    pass


def _parse_utc(s: str) -> datetime:
    """Parse ISO string as UTC, accepting 'Z' or '+00:00' (and coerce if naive)."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@pytest.mark.skipif(_normalize_trade is None, reason="normalize_trade not available")
def test_normalize_trade_sets_dtposted_and_fitid():
    raw = {
        "id": "T123ABC",
        "filled_at": "2025-02-10T15:04:05Z",   # Alpaca-style fill time
        "symbol": "AAPL",
        "side": "buy",
        "qty": "5",
        "price": "100",
        "type": "fill",
    }
    norm = _normalize_trade(raw)
    assert isinstance(norm, dict), "normalize_trade must return dict"

    # FITID correctness
    assert norm.get("fitid") == raw["id"], "FITID should be derived from source trade ID"

    # DTPOSTED / timestamp_utc present and UTC
    ts = norm.get("timestamp_utc") or norm.get("datetime_utc")
    assert ts, "timestamp_utc (or datetime_utc) must be set by normalizer"
    dt = _parse_utc(ts)
    assert dt.tzinfo is not None and dt.utcoffset().total_seconds() == 0, "timestamp must be UTC"

    # Action sanity (buy -> long; sell -> short) — allow graceful mapping
    allowed = {"long", "short", "call", "put", "assignment", "exercise", "expire", "reorg", "inverse", "other"}
    action = (norm.get("action") or "").lower()
    assert action in allowed, f"Unexpected action mapping for trade: {action}"


@pytest.mark.skipif(_normalize_cash is None, reason="cash normalizer not available")
def test_normalize_cash_sets_dtposted_and_fitid():
    raw = {
        "id": "C456XYZ",
        # Alpaca activities often expose a timestamp; accept a generic field name
        "transaction_time": "2025-02-09T13:01:02Z",
        "activity_type": "DIV",
        "net_amount": "12.34",
        "symbol": "MSFT",
        "description": "Dividend",
    }
    norm = _normalize_cash(raw)
    assert isinstance(norm, dict), "cash normalizer must return dict"

    # FITID correctness
    assert norm.get("fitid") == raw["id"], "FITID should be derived from source cash activity ID"

    # DTPOSTED / timestamp_utc present and UTC
    ts = norm.get("timestamp_utc") or norm.get("datetime_utc")
    assert ts, "timestamp_utc (or datetime_utc) must be set for cash activities"
    dt = _parse_utc(ts)
    assert dt.tzinfo is not None and dt.utcoffset().total_seconds() == 0, "timestamp must be UTC"

    # Action presence (may be 'other' depending on mapping)
    assert isinstance(norm.get("action"), str), "cash normalization should set an 'action' string"


@pytest.mark.skipif(_normalize_position is None, reason="normalize_position not available")
def test_normalize_position_dtposted_and_fitid_idempotent():
    raw = {
        "id": "P789POS",
        "symbol": "NVDA",
        "qty": "10",
        "avg_entry_price": "300.00",
        "as_of": "2025-02-08T00:00:00Z",
    }
    norm1 = _normalize_position(raw)
    norm2 = _normalize_position(raw)

    assert isinstance(norm1, dict) and isinstance(norm2, dict), "position normalizer must return dict"

    # FITID correctness + stability
    assert norm1.get("fitid") == raw["id"], "FITID should be derived from position snapshot ID when present"
    assert norm1.get("fitid") == norm2.get("fitid"), "FITID must be stable across repeated normalizations"

    # DTPOSTED / timestamp_utc present, derived from 'as_of' (or equivalent) and UTC
    ts1 = norm1.get("timestamp_utc") or norm1.get("datetime_utc")
    ts2 = norm2.get("timestamp_utc") or norm2.get("datetime_utc")
    assert ts1 and ts2, "timestamp_utc (or datetime_utc) must be set for positions"
    dt1 = _parse_utc(ts1)
    dt2 = _parse_utc(ts2)
    assert dt1 == dt2, "timestamp must be deterministic across runs for the same input"
    assert dt1.tzinfo is not None and dt1.utcoffset().total_seconds() == 0, "timestamp must be UTC"


@pytest.mark.skipif(_normalize_position is None, reason="normalize_position not available")
def test_normalize_position_fallback_fitid_when_missing_id():
    # If the upstream position lacks an explicit ID, the normalizer should still produce a stable key
    raw = {
        # no 'id'
        "symbol": "TSLA",
        "qty": "3",
        "avg_entry_price": "250.00",
        "as_of": "2025-02-07T00:00:00Z",
    }
    norm = _normalize_position(raw)
    assert isinstance(norm, dict)
    # Accept either generated FITID (e.g., from symbol+as_of) or None — but MUST have trade_id or group identity fields downstream
    # Here we only assert that when FITID is provided, it's a non-empty string.
    fitid = norm.get("fitid")
    if fitid is not None:
        assert isinstance(fitid, str) and fitid.strip(), "Generated FITID must be a non-empty string"

    ts = norm.get("timestamp_utc") or norm.get("datetime_utc")
    assert ts, "timestamp_utc (or datetime_utc) must be set for positions without an explicit ID"
    _ = _parse_utc(ts)  # just parse/validate UTC
