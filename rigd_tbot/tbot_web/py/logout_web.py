# tbot_web/py/logout_web.py
# Handles user logout and session termination

from flask import Blueprint, redirect, url_for, session
from tbot_bot.support.utils_log import log_event

logout_blueprint = Blueprint("logout_web", __name__)

@logout_blueprint.route("/logout")
def logout():
    """
    Logs out the current user by clearing the session and redirecting to the login page.
    """
    username = session.get("user", "Unknown")
    session.pop("authenticated", None)
    session.pop("user", None)
    log_event("logout_web", f"User '{username}' logged out.")
    return redirect(url_for("login_web.login"))
