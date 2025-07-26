# tbot_web/support/utils_web.py
# Web-specific utility functions and helpers for RIGD TradeBot Web UI

import functools
from flask import session, redirect, url_for, flash, request, has_request_context
from datetime import datetime, timedelta
from typing import Callable, Any, Optional

# Constants
SESSION_TIMEOUT_SECONDS = 3600  # 1 hour session timeout by default

def utc_now_iso() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.utcnow().isoformat()

def login_required(func: Callable) -> Callable:
    """
    Decorator to require user login for Flask routes.
    Redirects to login page if no user in session.
    Safe in sessionless environments (test).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not has_request_context():
            return func(*args, **kwargs)
        if not session.get("authenticated"):
            flash("Please login to access this page.", "warning")
            return redirect(url_for("login_web.login"))
        return func(*args, **kwargs)
    return wrapper

def role_required(required_role: str):
    """
    Decorator factory to require a specific user role.
    Requires session to have 'role' attribute.
    Safe in sessionless environments (test).
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not has_request_context():
                return func(*args, **kwargs)
            user_role = session.get("role", None)
            if user_role != required_role:
                flash("You do not have permission to access this page.", "error")
                return redirect(url_for("login_web.login"))
            return func(*args, **kwargs)
        return wrapper
    return decorator

def admin_required(func: Callable) -> Callable:
    """
    Decorator to require admin role for Flask routes.
    Safe in sessionless environments (test).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not has_request_context():
            return func(*args, **kwargs)
        user_role = session.get("role", None)
        if user_role != "admin":
            flash("Admin privileges required.", "error")
            return redirect(url_for("login_web.login"))
        return func(*args, **kwargs)
    return wrapper

def is_admin() -> bool:
    """
    Returns True if current user session is admin.
    Safe in sessionless environments (test).
    """
    if not has_request_context():
        return False
    return session.get("role", None) == "admin"

def safe_int(value: Optional[str], default: int = 0) -> int:
    """
    Converts a string to int safely, returning default if conversion fails.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_float(value: Optional[str], default: float = 0.0) -> float:
    """
    Converts a string to float safely, returning default if conversion fails.
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def get_client_ip() -> str:
    """
    Attempts to retrieve the client's IP address from the Flask request context.
    Supports X-Forwarded-For header if behind proxies.
    """
    if has_request_context():
        if request.headers.get("X-Forwarded-For"):
            ip = request.headers.get("X-Forwarded-For").split(",")[0].strip()
        else:
            ip = request.remote_addr or "unknown"
        return ip
    return "unknown"

def flash_and_log(message: str, category: str = "info", logger=None, log_level: str = "info"):
    """
    Flash a message to the user and optionally log it.
    Safe in sessionless environments (test).
    """
    if has_request_context():
        flash(message, category)
    if logger:
        log_func = getattr(logger, log_level, None)
        if callable(log_func):
            log_func(message)

def get_session_duration() -> int:
    """
    Returns current session duration in seconds, or 0 if no session start recorded.
    Safe in sessionless environments (test).
    """
    if not has_request_context():
        return 0
    start = session.get("session_start")
    if not start:
        return 0
    start_dt = datetime.fromisoformat(start)
    return int((datetime.utcnow() - start_dt).total_seconds())

def update_session_timestamp():
    """
    Updates the session start timestamp to current UTC ISO format.
    Safe in sessionless environments (test).
    """
    if has_request_context():
        session["session_start"] = utc_now_iso()

def clear_session():
    """
    Clears the current user session safely.
    Safe in sessionless environments (test).
    """
    if has_request_context():
        session.clear()

def format_datetime(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S UTC") -> str:
    """
    Format a datetime object for display in UI templates.
    """
    if not dt:
        return ""
    return dt.strftime(fmt)

# Add any additional web-specific utilities here as needed.
