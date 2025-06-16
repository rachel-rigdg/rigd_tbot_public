# tbot_web/py/register_web.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from tbot_web.support.auth_web import upsert_user, get_db_connection
from sqlite3 import OperationalError
from pathlib import Path

register_web = Blueprint("register_web", __name__, url_prefix="/registration")

BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"

def user_exists():
    try:
        conn = get_db_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM system_users;")
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except OperationalError:
        return False

@register_web.route("/", methods=["GET", "POST"])
def register_page():
    already_exists = user_exists()
    if already_exists:
        try:
            if BOT_STATE_PATH.exists():
                state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
                if state == "registration":
                    with open(BOT_STATE_PATH, "w", encoding="utf-8") as f:
                        f.write("idle")
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
        try:
            upsert_user(username, password, email)
            flash("Admin user created successfully. Please log in.", "success")
            try:
                if BOT_STATE_PATH.exists():
                    state = BOT_STATE_PATH.read_text(encoding="utf-8").strip()
                    if state == "registration":
                        with open(BOT_STATE_PATH, "w", encoding="utf-8") as f:
                            f.write("idle")
            except Exception:
                pass
            session.clear()
            return redirect(url_for("login_web.login"))
        except Exception as e:
            flash(f"Error creating user: {e}", "error")
            return render_template("register.html", username=username, email=email)
    return render_template("register.html")
