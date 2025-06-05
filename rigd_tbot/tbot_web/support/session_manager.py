# tbot_web/support/session_manager.py
# Manages user session lifecycle and state persistence for RIGD TradeBot Web UI

from flask import session, redirect, url_for, flash
from datetime import datetime, timedelta

SESSION_TIMEOUT_SECONDS = 3600  # Default session timeout (1 hour)

def start_session(username: str, user_role: str) -> None:
    """
    Initialize session data for a logged-in user.
    Stores username, role, and session start timestamp (UTC ISO format).
    """
    session.clear()
    session['username'] = username
    session['user_role'] = user_role
    session['session_start'] = datetime.utcnow().isoformat()

def is_session_active() -> bool:
    """
    Checks if the current session is active and not expired.
    Returns True if session is valid, False if expired or missing.
    """
    start = session.get('session_start')
    if not start:
        return False
    try:
        start_dt = datetime.fromisoformat(start)
    except Exception:
        return False

    now = datetime.utcnow()
    elapsed = (now - start_dt).total_seconds()
    return elapsed <= SESSION_TIMEOUT_SECONDS

def extend_session() -> None:
    """
    Updates session start timestamp to extend active session.
    Call this on user activity to keep session alive.
    """
    session['session_start'] = datetime.utcnow().isoformat()

def end_session() -> None:
    """
    Clear all session data to effectively log out user.
    """
    session.clear()

def require_active_session():
    """
    Decorator to enforce active session on Flask routes.
    Redirects to login page with flash if session expired or inactive.
    """
    from functools import wraps
    from flask import request

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not is_session_active() or 'username' not in session:
                flash("Session expired or not logged in. Please log in again.", "warning")
                return redirect(url_for('login_web.login', next=request.path))
            extend_session()  # refresh session timer on valid request
            return func(*args, **kwargs)
        return wrapper
    return decorator
