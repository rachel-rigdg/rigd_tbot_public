# tbot_bot/support/utils_time.py
 # Time utilities for UTC, timestamps, and scheduling


from datetime import datetime, timezone

def utc_now():
    """Returns the current UTC datetime object with tzinfo."""
    return datetime.utcnow().replace(tzinfo=timezone.utc)
