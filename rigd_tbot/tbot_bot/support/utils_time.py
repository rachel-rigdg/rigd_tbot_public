# tbot_bot/support/utils_time.py
# Time utilities for UTC, local timezone, timestamps, and scheduling (centralized, config-driven)

from datetime import datetime, time as dt_time, timedelta
import re
import pytz
from pytz import AmbiguousTimeError, NonExistentTimeError

from tbot_bot.config.env_bot import get_bot_config

# -----------------------------
# NEW: HH:MM validator (strict 24h)
# -----------------------------
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

def validate_hhmm(timestr: str) -> bool:
    """
    Return True if timestr is 'HH:MM' 24-hour format.
    """
    if timestr is None:
        return False
    return bool(_HHMM_RE.match(str(timestr).strip()))


def utc_now():
    """Returns the current UTC datetime object with tzinfo."""
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

def now_local():
    """Returns the current local time as a timezone-aware datetime, per config TIMEZONE."""
    tz = get_timezone()
    return utc_now().astimezone(tz)

def time_local():
    """Returns the current local time as a dt_time object (for window comparisons)."""
    return now_local().time()

def parse_time_local(tstr):
    """
    Parses a 'HH:MM' string and returns a dt_time object in the configured local timezone.
    Accepts already-dt_time input and returns unchanged.
    """
    if isinstance(tstr, dt_time):
        return tstr
    h, m = map(int, str(tstr).strip().split(":"))
    return dt_time(hour=h, minute=m)

def ensure_time_obj(val):
    """
    Converts a string 'HH:MM' or dt_time to dt_time object.
    Always returns dt_time for robust time comparisons.
    """
    if isinstance(val, dt_time):
        return val
    h, m = map(int, str(val).strip().split(":"))
    return dt_time(hour=h, minute=m)

def is_now_in_window(start: str, end: str):
    """
    Returns True if the current local time is within [start, end), where start/end are 'HH:MM' or dt_time.
    """
    now_t = time_local()
    s = ensure_time_obj(start)
    e = ensure_time_obj(end)
    if s <= e:
        return s <= now_t < e
    # Handles overnight windows (e.g., 23:00-02:00)
    return now_t >= s or now_t < e

def to_local(dt_obj):
    """Converts a UTC dt/datetime to configured local timezone."""
    tz = get_timezone()
    if dt_obj.tzinfo is None:
        dt_obj = pytz.UTC.localize(dt_obj)
    return dt_obj.astimezone(tz)

def to_utc(dt_obj):
    """Converts a local dt/datetime to UTC."""
    if dt_obj.tzinfo is None:
        return pytz.UTC.localize(dt_obj)
    return dt_obj.astimezone(pytz.UTC)

# -----------------------------
# NEW: Market-day aware reference date
# -----------------------------
def nearest_market_day_reference(now_utc=None, tzstr: str = None):
    """
    Pick a date (in the given timezone) to anchor LOCAL→UTC conversions for market session times.
    Rules:
      - If local time is Sat/Sun -> next Monday.
      - If local time >= 18:00 (after-hours) -> next weekday (handles "saved after close").
      - If local time < 06:00 (pre-dawn ops) -> previous weekday.
      - Else -> today (weekday).
    This helps avoid DST edge cases across late-night saves near transitions.
    """
    if now_utc is None:
        now_utc = utc_now()
    tz = pytz.timezone(tzstr) if tzstr else get_timezone()
    now_local = now_utc.astimezone(tz)
    d = now_local.date()
    wd = now_local.weekday()  # 0=Mon .. 6=Sun

    def next_weekday(date_obj):
        while date_obj.weekday() >= 5:  # Sat/Sun
            date_obj += timedelta(days=1)
        return date_obj

    def prev_weekday(date_obj):
        while date_obj.weekday() >= 5:  # Sat/Sun
            date_obj -= timedelta(days=1)
        return date_obj

    # Weekend -> next Monday
    if wd >= 5:
        return next_weekday(d + timedelta(days=1))
    # After-hours (>= 18:00 local) -> use next weekday
    if now_local.hour >= 18:
        return next_weekday(d + timedelta(days=1))
    # Very early morning (< 06:00) -> anchor on previous weekday
    if now_local.hour < 6:
        return prev_weekday(d - timedelta(days=1))
    # Otherwise use today (weekday business day)
    return d

# -----------------------------
# NEW: LOCAL 'HH:MM' -> UTC 'HH:MM' (DST-aware, anchored to reference date)
# -----------------------------
def local_hhmm_to_utc_hhmm(timestr: str, tzstr: str, reference_date=None) -> str:
    """
    Convert a local 'HH:MM' (in tzstr) to a UTC 'HH:MM' string.
    - Validates HH:MM format.
    - Anchors conversion to `reference_date` in tzstr if provided; otherwise uses nearest_market_day_reference().
    - Handles DST ambiguous/non-existent times by choosing a safe interpretation.
    """
    if not validate_hhmm(timestr):
        raise ValueError(f"Invalid HH:MM value: '{timestr}'")

    tz = pytz.timezone(tzstr)
    if reference_date is None:
        reference_date = nearest_market_day_reference(utc_now(), tzstr)

    hh, mm = map(int, timestr.split(":"))
    naive_local_dt = datetime(reference_date.year, reference_date.month, reference_date.day, hh, mm)

    # Handle DST anomalies
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
