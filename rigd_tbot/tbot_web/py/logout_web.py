# tbot_web/py/logout_web.py
# Handles user logout and session termination

from flask import Blueprint, redirect, url_for, session
from tbot_web.support.utils_log import log_event  # Corrected import per directory spec

logout_blueprint = Blueprint("logout_web", __name__)

@logout_blueprint.route("/logout")
def logout():
    """
    Logs out the current user by clearing the session and redirecting to the login page.
    """
    username = session.get("user", "Unknown")
    session.clear()
    log_event("logout_web", f"User '{username}' logged out.")
    return redirect(url_for("login_web.login"))
