# tests/time/test_utils_time.py
# Unit tests for timezone handling utilities in tbot_bot.support.utils_time

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import math

import pytest

from tbot_bot.support.utils_time import (
    to_tz,
    utc_from_tz,
)

# ---------------------------
# Helpers
# ---------------------------
NY_TZ = "America/New_York"


def _rough_equal(a: datetime, b: datetime, tol_seconds: int = 0) -> bool:
    """Compare two aware datetimes allowing for a small tolerance."""
    if a.tzinfo is None or b.tzinfo is None:
        return False
    return abs((a - b).total_seconds()) <= tol_seconds


# ---------------------------
# Tests
# ---------------------------

def test_utc_has_no_dst_shift_across_boundaries():
    """
    Verify that UTC itself does not observe DST: offset remains zero
    and arithmetic across DST boundaries keeps tz as UTC with no shifts.
    We'll step across a US DST transition (second Sunday in March / first Sunday in November),
    but only inspect UTC properties.
    """
    # Around the 2025 US DST start (Mar 9, 2025 @ 07:00 UTC)
    before = datetime(2025, 3, 9, 6, 30, tzinfo=timezone.utc)
    after = datetime(2025, 3, 9, 7, 30, tzinfo=timezone.utc)  # cross DST boundary for US, but not for UTC
    assert before.tzinfo == timezone.utc
    assert after.tzinfo == timezone.utc
    # Offsets are zero, tzname is 'UTC'
    assert before.utcoffset() == timedelta(0)
    assert after.utcoffset() == timedelta(0)
    assert before.tzname() == "UTC"
    assert after.tzname() == "UTC"
    # Arithmetic remains consistent
    assert (after - before) == timedelta(hours=1)


def test_to_tz_new_york_edst_and_est_offsets_and_names():
    """
    Converting the same wall-clock UTC hour to America/New_York yields:
      - EDT (UTC-4) in June
      - EST (UTC-5) in December
    """
    # Pick a neutral UTC wall-clock time in mid-year and end-year
    june_utc = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
    dec_utc = datetime(2025, 12, 15, 12, 0, tzinfo=timezone.utc)

    june_ny = to_tz(june_utc, NY_TZ)
    dec_ny = to_tz(dec_utc, NY_TZ)

    # Check tzname and offsets
    assert june_ny.tzname() in {"EDT"}  # Daylight time
    assert dec_ny.tzname() in {"EST"}   # Standard time

    # Offsets: -4 hours for EDT, -5 hours for EST
    assert june_ny.utcoffset() == timedelta(hours=-4)
    assert dec_ny.utcoffset() == timedelta(hours=-5)

    # Sanity check the converted local hours
    assert june_ny.hour == 8   # 12:00 UTC -> 08:00 EDT
    assert dec_ny.hour == 7    # 12:00 UTC -> 07:00 EST


def test_roundtrip_utc_from_tz_identity():
    """
    Round-trip: UTC -> local TZ -> UTC should be identity (same instant).
    """
    base_utc = datetime(2025, 4, 1, 15, 27, 42, tzinfo=timezone.utc)
    ny_local = to_tz(base_utc, NY_TZ)
    back_utc = utc_from_tz(ny_local, NY_TZ)

    # Exact equality on instant (and tzinfo == UTC)
    assert back_utc.tzinfo == timezone.utc
    assert _rough_equal(base_utc, back_utc, tol_seconds=0)
