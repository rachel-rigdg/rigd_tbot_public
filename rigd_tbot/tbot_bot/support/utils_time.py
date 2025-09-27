# tbot_bot/support/utils_time.py
# Time utilities for UTC, local timezone, timestamps, and scheduling (centralized, config-driven)

from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Optional
import re
from zoneinfo import ZoneInfo

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
def _safe_zoneinfo(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")

def get_timezone() -> ZoneInfo:
    """
    Returns the ZoneInfo timezone object from config['TIMEZONE'].
    Defaults to UTC if missing or invalid.
    """
    config = get_bot_config() or {}
    tz_name = (config.get("TIMEZONE") or "UTC").strip()
    return _safe_zoneinfo(tz_name)

def now_utc() -> datetime:
    """Return the current UTC datetime (aware, no DST applied)."""
    return datetime.now(timezone.utc)

# Back-compat alias if older code imports utc_now()
utc_now = now_utc

def now_local() -> datetime:
    """Return the current local datetime (aware), per config TIMEZONE."""
    return now_utc().astimezone(get_timezone())

def time_local() -> dt_time:
    """Return the current local clock time as a dt_time (for window comparisons)."""
    return now_local().time()

def to_local(dt_obj: datetime) -> datetime:
    """
    Convert a datetime to configured local timezone.
    If dt_obj is naive, treat it as UTC (conservative convention).
    """
    tz = get_timezone()
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj.astimezone(tz)

def to_utc(dt_obj: datetime) -> datetime:
    """
    Convert a datetime to UTC.
    If dt_obj is naive, assume it is in the configured local timezone, then convert to UTC.
    No DST math applied to UTC itself; conversion is tz-aware via ZoneInfo.
    """
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=get_timezone())
    return dt_obj.astimezone(timezone.utc)

# -----------------------------
# New normalized helpers (explicit API)
# -----------------------------
def fmt_iso_utc(dt_obj: datetime) -> str:
    """Format a datetime as ISO-8601 UTC string with trailing 'Z'."""
    dt_u = to_utc(dt_obj)
    return dt_u.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

def to_tz(dt_obj: datetime, tz_str: str) -> datetime:
    """
    Convert an aware (or naive=UTC) datetime to a specific IANA timezone.
    DST-handling is inherent in ZoneInfo; no manual offset math.
    """
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj.astimezone(_safe_zoneinfo(tz_str))

def utc_from_tz(local_dt: datetime, tz_str: str) -> datetime:
    """
    Interpret a wall-clock datetime in tz_str and convert to UTC.
    If local_dt is naive, assume it is expressed in tz_str.
    """
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=_safe_zoneinfo(tz_str))
    else:
        # Re-interpret only if it's not already in the intended tz
        local_dt = local_dt.astimezone(_safe_zoneinfo(tz_str))
    return local_dt.astimezone(timezone.utc)

def _fmt_date_hhmm(dt_obj: datetime) -> str:
    """YYYY-MM-DD, HH:MM (24h)"""
    return dt_obj.strftime("%Y-%m-%d, %H:%M")

def _fmt_ampm(dt_obj: datetime) -> str:
    """h:mm AM/PM without leading zero on hour (portable)."""
    s = dt_obj.strftime("%I:%M %p")
    return s.lstrip("0") if s.startswith("0") else s

def clock_payload(tz_str: str) -> dict:
    """
    Build read-only clock payload for UI:
      {
        "utc_iso": "YYYY-MM-DD, HH:MM",
        "market_utc_iso": "YYYY-MM-DD, HH:MM",
        "market_local": "h:mm AM/PM",
        "local_utc_iso": "YYYY-MM-DD, HH:MM",
        "local_local": "h:mm AM/PM"
      }
    - UTC has no DST conversion.
    - Market shows both the UTC-equivalent and local wall time for tz_str.
    - Local shows both UTC-equivalent and the machine's local wall time.
    """
    # Ground truth
    utc_now_dt = now_utc()

    # Market
    market_tz = _safe_zoneinfo(tz_str)
    market_local = utc_now_dt.astimezone(market_tz)
    market_utc = market_local.astimezone(timezone.utc)

    # Machine local (OS zone)
    machine_local = utc_now_dt.astimezone()  # system tz
    machine_utc = machine_local.astimezone(timezone.utc)

    return {
        "utc_iso": _fmt_date_hhmm(utc_now_dt),
        "market_utc_iso": _fmt_date_hhmm(market_utc),
        "market_local": _fmt_ampm(market_local),
        "local_utc_iso": _fmt_date_hhmm(machine_utc),
        "local_local": _fmt_ampm(machine_local),
    }

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
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

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
    when = ensure_aware_utc(when) or now_utc()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(isoformat_utc_z(when), encoding="utf-8")

def has_run_today(stamp_path: Path, now_utc_dt: Optional[datetime] = None) -> bool:
    """True if the stamp file records a run on the same UTC calendar day as now."""
    ts = read_utc_stamp(stamp_path)
    now = ensure_aware_utc(now_utc_dt) or now_utc()
    return bool(ts and ts.date() == now.date())

# -----------------------------
# Market-day aware reference date (LOCAL)
# -----------------------------
def nearest_market_day_reference(now_utc_dt: Optional[datetime] = None, tzstr: Optional[str] = None):
    """
    Pick a date (in the given timezone) to anchor LOCAL→UTC conversions for market session times.
    Rules:
      - If local time is Sat/Sun -> next Monday.
      - If local time >= 18:00 (after-hours) -> next weekday (handles "saved after close").
      - If local time < 06:00 (pre-dawn ops) -> previous weekday.
      - Else -> today (weekday).
    """
    if now_utc_dt is None:
        now_utc_dt = now_utc()
    tz = _safe_zoneinfo(tzstr) if tzstr else get_timezone()
    now_loc = now_utc_dt.astimezone(tz)
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
# LOCAL 'HH:MM' -> UTC 'HH:MM' (DST-aware via ZoneInfo, anchored)
# -----------------------------
def local_hhmm_to_utc_hhmm(timestr: str, tzstr: Optional[str] = None, reference_date=None) -> str:
    """
    Convert a local 'HH:MM' (in tzstr or configured TZ) to a UTC 'HH:MM' string.
    - Validates HH:MM format.
    - Anchors conversion to `reference_date` in tzstr if provided; otherwise uses nearest_market_day_reference().
    - Conversion is tz-aware via ZoneInfo; no manual DST adjustments.
    """
    if not validate_hhmm(timestr):
        raise ValueError(f"Invalid HH:MM value: '{timestr}'")

    tz = _safe_zoneinfo(tzstr) if tzstr else get_timezone()
    if reference_date is None:
        reference_date = nearest_market_day_reference(now_utc(), getattr(tz, "key", None))

    hh, mm = map(int, timestr.split(":"))
    # Interpret wall-clock time in the target tz for the reference date
    local_dt = datetime(reference_date.year, reference_date.month, reference_date.day, hh, mm, tzinfo=tz)
    utc_dt = local_dt.astimezone(timezone.utc)
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

def scheduled_run_utc(hhmm_utc: str, now_utc_dt: Optional[datetime] = None) -> datetime:
    """
    Given 'HH:MM' in UTC, return the aware UTC datetime for 'today' at that time.
    """
    now = ensure_aware_utc(now_utc_dt) or now_utc()
    t = parse_hhmm_utc(hhmm_utc)
    return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
