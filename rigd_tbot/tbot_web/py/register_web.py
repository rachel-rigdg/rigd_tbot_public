# tbot_web/py/register_web.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from tbot_web.support.auth_web import upsert_user, get_db_connection
from sqlite3 import OperationalError
from pathlib import Path
import sys
from tbot_bot.support.bot_state_manager import get_state, set_state  # ADDED

register_web = Blueprint("register_web", __name__, url_prefix="/registration")


def user_exists():
    try:
        conn = get_db_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM system_users;")
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except OperationalError:
        return False


def get_next_user_role():
    """Assign 'admin' to first user, else 'viewer' by default."""
    try:
        conn = get_db_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM system_users;")
        count = cursor.fetchone()[0]
        conn.close()
        if count == 0:
            return "admin"
        return "viewer"
    except Exception:
        return "admin"


@register_web.route("/", methods=["GET", "POST"])
def register_page():
    already_exists = user_exists()
    if already_exists:
        try:
            state = (get_state() or "").strip()  # CHANGED
            if state == "registration":
                set_state("running", reason="web:post-registration")  # CHANGED
        except Exception:
            pass
        session.clear()
        flash("Admin user already exists. Please log in.", "info")
        return redirect(url_for("login_web.login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not username or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html", username=username, email=email)
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("register.html", username=username, email=email)
        role = get_next_user_role()
        try:
            upsert_user(username, password, email, role=role)
            flash(f"{role.capitalize()} user created successfully. Please log in.", "success")
            try:
                state = (get_state() or "").strip()  # CHANGED
                if state == "registration":
                    set_state("idle", reason="web:registration")  # CHANGED
            except Exception:
                pass
            session.clear()
            return redirect(url_for("login_web.login"))
        except Exception as e:
            flash(f"Error creating user: {e}", "error")
            return render_template("register.html", username=username, email=email)
    return render_template("register.html")
