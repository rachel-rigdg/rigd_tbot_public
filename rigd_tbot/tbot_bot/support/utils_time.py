# tbot_bot/support/utils_time.py
# Time utilities for UTC, local timezone, timestamps, and scheduling (centralized, config-driven)

from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Optional
import re
import pytz
from pytz import AmbiguousTimeError, NonExistentTimeError

from tbot_bot.config.env_bot import get_bot_config

# -----------------------------
# HH:MM validator (strict 24h)
# -----------------------------
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

def validate_hhmm(timestr: str) -> bool:
    """Return True if timestr is 'HH:MM' 24-hour format."""
    if timestr is None:
        return False
    return bool(_HHMM_RE.match(str(timestr).strip()))

# -----------------------------
# Core "now" and timezone helpers
# -----------------------------
def utc_now() -> datetime:
    """Return the current UTC datetime (aware)."""
    return datetime.utcnow().replace(tzinfo=pytz.UTC)

def get_timezone():
    """
    Returns the pytz timezone object from config['TIMEZONE'].
    Defaults to UTC if missing or invalid.
    """
    config = get_bot_config()
    tz_name = config.get("TIMEZONE", "UTC")
    try:
        return pytz.timezone(tz_name)
    except Exception:
        return pytz.UTC

def now_local() -> datetime:
    """Return the current local datetime (aware), per config TIMEZONE."""
    tz = get_timezone()
    return utc_now().astimezone(tz)

def time_local() -> dt_time:
    """Return the current local clock time as a dt_time (for window comparisons)."""
    return now_local().time()

def to_local(dt_obj: datetime) -> datetime:
    """
    Convert a datetime to configured local timezone.
    If dt_obj is naive, treat it as UTC (common convention in our codebase).
    """
    tz = get_timezone()
    if dt_obj.tzinfo is None:
        dt_obj = pytz.UTC.localize(dt_obj)
    return dt_obj.astimezone(tz)

def to_utc(dt_obj: datetime) -> datetime:
    """
    Convert a datetime to UTC.
    If dt_obj is naive, assume it is in the configured local timezone,
    then convert to UTC (handles DST gaps/ambiguity).
    """
    if dt_obj.tzinfo is None:
        tz = get_timezone()
        try:
            local_dt = tz.localize(dt_obj, is_dst=None)
        except AmbiguousTimeError:
            local_dt = tz.localize(dt_obj, is_dst=False)  # prefer standard time
        except NonExistentTimeError:
            local_dt = tz.localize(dt_obj + timedelta(hours=1), is_dst=True)  # skip spring-forward gap
        return local_dt.astimezone(pytz.UTC)
    return dt_obj.astimezone(pytz.UTC)

# -----------------------------
# Small parsing helpers (local clock)
# -----------------------------
def parse_time_local(tstr) -> dt_time:
    """
    Parse 'HH:MM' to dt_time. If already dt_time, return as-is.
    (This is a clock-time object; it does not carry tzinfo.)
    """
    if isinstance(tstr, dt_time):
        return tstr
    s = str(tstr).strip()
    if not validate_hhmm(s):
        raise ValueError(f"Invalid HH:MM value: '{tstr}'")
    h, m = map(int, s.split(":"))
    return dt_time(hour=h, minute=m)

def ensure_time_obj(val) -> dt_time:
    """
    Convert a string 'HH:MM' or dt_time to dt_time.
    Always returns dt_time for robust time comparisons.
    """
    if isinstance(val, dt_time):
        return val
    s = str(val).strip()
    if not validate_hhmm(s):
        raise ValueError(f"Invalid HH:MM value: '{val}'")
    h, m = map(int, s.split(":"))
    return dt_time(hour=h, minute=m)

def is_now_in_window(start: str, end: str) -> bool:
    """
    Return True if the current local time is within [start, end),
    where start/end are 'HH:MM' or dt_time. Handles overnight windows.
    """
    now_t = time_local()
    s = ensure_time_obj(start)
    e = ensure_time_obj(end)
    if s <= e:
        return s <= now_t < e
    # Overnight window (e.g., 23:00-02:00)
    return now_t >= s or now_t < e

# -----------------------------
# Aware UTC helpers + ISO stamps
# -----------------------------
def ensure_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a datetime to timezone-aware UTC; pass through None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)

def parse_iso_utc(s: str) -> datetime:
    """
    Parse an ISO-8601 string to an aware UTC datetime.
    Accepts '...Z' or offsets like '+00:00'. Raises on invalid.
    """
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return ensure_aware_utc(dt)

def isoformat_utc_z(dt: datetime) -> str:
    """Format an aware datetime as ISO-8601 with trailing 'Z'."""
    return ensure_aware_utc(dt).isoformat().replace("+00:00", "Z")

def read_utc_stamp(path: Path) -> Optional[datetime]:
    """Read ISO-8601 (including trailing Z) from file and return aware UTC dt."""
    if not path.exists():
        return None
    try:
        txt = path.read_text(encoding="utf-8").strip()
        return parse_iso_utc(txt)
    except Exception:
        return None

def write_utc_stamp(path: Path, when: datetime) -> None:
    """Write aware UTC datetime to file as ISO-8601 with trailing 'Z'."""
    when = ensure_aware_utc(when) or utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(isoformat_utc_z(when), encoding="utf-8")

def has_run_today(stamp_path: Path, now_utc: Optional[datetime] = None) -> bool:
    """True if the stamp file records a run on the same UTC calendar day as now."""
    ts = read_utc_stamp(stamp_path)
    now = ensure_aware_utc(now_utc) or utc_now()
    return bool(ts and ts.date() == now.date())

# -----------------------------
# Market-day aware reference date (LOCAL)
# -----------------------------
def nearest_market_day_reference(now_utc: Optional[datetime] = None, tzstr: Optional[str] = None):
    """
    Pick a date (in the given timezone) to anchor LOCAL→UTC conversions for market session times.
    Rules:
      - If local time is Sat/Sun -> next Monday.
      - If local time >= 18:00 (after-hours) -> next weekday (handles "saved after close").
      - If local time < 06:00 (pre-dawn ops) -> previous weekday.
      - Else -> today (weekday).
    Helps avoid DST edge cases around late-night saves near transitions.
    """
    if now_utc is None:
        now_utc = utc_now()
    tz = pytz.timezone(tzstr) if tzstr else get_timezone()
    now_loc = now_utc.astimezone(tz)
    d = now_loc.date()
    wd = now_loc.weekday()  # 0=Mon..6=Sun

    def next_weekday(date_obj):
        while date_obj.weekday() >= 5:  # Sat/Sun
            date_obj += timedelta(days=1)
        return date_obj

    def prev_weekday(date_obj):
        while date_obj.weekday() >= 5:
            date_obj -= timedelta(days=1)
        return date_obj

    if wd >= 5:
        return next_weekday(d + timedelta(days=1))
    if now_loc.hour >= 18:
        return next_weekday(d + timedelta(days=1))
    if now_loc.hour < 6:
        return prev_weekday(d - timedelta(days=1))
    return d

# -----------------------------
# LOCAL 'HH:MM' -> UTC 'HH:MM' (DST-aware, anchored)
# -----------------------------
def local_hhmm_to_utc_hhmm(timestr: str, tzstr: Optional[str] = None, reference_date=None) -> str:
    """
    Convert a local 'HH:MM' (in tzstr or configured TZ) to a UTC 'HH:MM' string.
    - Validates HH:MM format.
    - Anchors conversion to `reference_date` in tzstr if provided; otherwise uses nearest_market_day_reference().
    - Handles DST ambiguous/non-existent times by choosing a safe interpretation.
    """
    if not validate_hhmm(timestr):
        raise ValueError(f"Invalid HH:MM value: '{timestr}'")

    tz = pytz.timezone(tzstr) if tzstr else get_timezone()
    if reference_date is None:
        reference_date = nearest_market_day_reference(utc_now(), tz.zone if hasattr(tz, "zone") else tzstr)

    hh, mm = map(int, timestr.split(":"))
    naive_local_dt = datetime(reference_date.year, reference_date.month, reference_date.day, hh, mm)

    try:
        local_dt = tz.localize(naive_local_dt, is_dst=None)
    except AmbiguousTimeError:
        # Prefer standard-time interpretation (is_dst=False) for determinism
        local_dt = tz.localize(naive_local_dt, is_dst=False)
    except NonExistentTimeError:
        # During "spring forward", choose the next valid time by adding 1 hour
        local_dt = tz.localize(naive_local_dt + timedelta(hours=1), is_dst=True)

    utc_dt = local_dt.astimezone(pytz.UTC)
    return utc_dt.strftime("%H:%M")

# -----------------------------
# UTC 'HH:MM' helpers
# -----------------------------
def parse_hhmm_utc(hhmm: str) -> dt_time:
    """Strict 'HH:MM' (UTC semantics). Falls back to 00:00 if invalid."""
    if not validate_hhmm(hhmm):
        return dt_time(0, 0)
    hh, mm = map(int, hhmm.split(":"))
    return dt_time(hour=hh, minute=mm)

def scheduled_run_utc(hhmm_utc: str, now_utc: Optional[datetime] = None) -> datetime:
    """
    Given 'HH:MM' in UTC, return the aware UTC datetime for 'today' at that time.
    """
    now = ensure_aware_utc(now_utc) or utc_now()
    t = parse_hhmm_utc(hhmm_utc)
    return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
