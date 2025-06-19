# tbot_web/py/login_web.py
# Login/logout route handling with rate limit enforcement

import os
from flask import Blueprint, request, redirect, render_template, session, url_for, flash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
from tbot_web.support.auth_web import validate_user, user_exists
from pathlib import Path

SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "300"))
API_LOGIN_LIMIT = os.getenv("API_LOGIN_LIMIT", "5/minute")
SECRET_KEY = os.getenv("SECRET_KEY", "use-secure-random-key-in-production")

login_blueprint = Blueprint("login_web", __name__, url_prefix="/login")
limiter = Limiter(get_remote_address, default_limits=[])

@limiter.limit(API_LOGIN_LIMIT)
@login_blueprint.route("/", methods=["GET", "POST"])
def login():
    """
    POST → Validate username and password against SYSTEM_USERS.db.
    GET  → Render login form.
    Redirect to /registration if no users exist.
    """
    if not user_exists():
        flash("No admin user exists. Please register.", "warning")
        return redirect(url_for("register_web.register_page"))
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if validate_user(username, password):
            session["authenticated"] = True
            session["user"] = username
            session["role"] = "admin"  # temporary fix for local admin
            return redirect(url_for("main.main_page"))
        else:
            return render_template("index.html", error="Invalid username or password")
    return render_template("index.html")

@login_blueprint.route("/logout")
def logout():
    """
    Clears session on logout.
    """
    session.pop("authenticated", None)
    session.pop("user", None)
    return redirect(url_for("login_web.login"))

def login_required(f):
    """
    Route guard to enforce login session for protected views.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login_web.login"))
        return f(*args, **kwargs)
    return decorated_function
