# tbot_bot/support/utils_time.py
# Time utilities for UTC, local timezone, timestamps, and scheduling (centralized, config-driven)

from datetime import datetime, time as dt_time
import pytz

from tbot_bot.config.env_bot import get_bot_config

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

def is_now_in_window(start: str, end: str):
    """
    Returns True if the current local time is within [start, end), where start/end are 'HH:MM' or dt_time.
    """
    now_t = time_local()
    s = parse_time_local(start)
    e = parse_time_local(end)
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
