# tbot_web/py/password_reset_web.py
# Handles user password reset and credential changes; ensures atomic Fernet key/secret rotation post-reset per RIGD spec

from flask import Blueprint, request, render_template, flash, redirect, url_for, session
from tbot_web.support.auth_web import upsert_user, get_db_connection  # Removed get_user_by_email import
from tbot_web.py.login_web import login_required
from pathlib import Path
import sys

from tbot_bot.support.config_fetch import get_live_config_for_rotation
from tbot_bot.config.provisioning_helper import rotate_all_keys_and_secrets
from tbot_bot.support.bootstrap_utils import is_first_bootstrap

password_reset_blueprint = Blueprint("password_reset_web", __name__, url_prefix="/password_reset")

BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

# Replace get_user_by_email call with equivalent using get_db_connection or modify as needed
def get_user_by_email(email: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, email, role FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"username": row[0], "email": row[1], "role": row[2]}
    return None

@password_reset_blueprint.route("/", methods=["GET", "POST"])
def request_reset():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        user = get_user_by_email(email)
        if not user:
            flash("No account with that email address.", "error")
            return render_template("password_reset_request.html")
        # Normally, an email with token would be sent here.
        session["reset_email"] = email
        return redirect(url_for("password_reset_web.reset_password"))
    return render_template("password_reset_request.html")

@password_reset_blueprint.route("/reset", methods=["GET", "POST"])
def reset_password():
    email = session.get("reset_email", None)
    if not email:
        flash("Session expired or invalid reset attempt.", "error")
        return redirect(url_for("password_reset_web.request_reset"))
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not password:
            flash("Password is required.", "error")
            return render_template("password_reset_form.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("password_reset_form.html")
        try:
            upsert_user(email, password, email, role=None)  # Only updates password, keeps role unchanged
            # Only rotate keys/secrets post-bootstrap
            if not is_first_bootstrap():
                config = get_live_config_for_rotation()
                if config:
                    rotate_all_keys_and_secrets(config)
            flash("Password reset successfully. Please log in.", "success")
            session.pop("reset_email", None)
            return redirect(url_for("login_web.login"))
        except Exception as e:
            flash(f"Error resetting password: {e}", "error")
            return render_template("password_reset_form.html")
    return render_template("password_reset_form.html")

@password_reset_blueprint.route("/cancel", methods=["POST"])
def cancel_reset():
    session.pop("reset_email", None)
    return redirect(url_for("login_web.login"))
