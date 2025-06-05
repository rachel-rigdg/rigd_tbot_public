# tbot_web/py/login_web.py
# Login/logout route handling with rate limit enforcement

import os
from flask import Blueprint, request, redirect, render_template, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
from tbot_web.support.auth_web import decrypt_password  # Corrected absolute import as per directory spec
from pathlib import Path
import json

# === Secure session config ===
SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "300"))
API_LOGIN_LIMIT = os.getenv("API_LOGIN_LIMIT", "5/minute")
SECRET_KEY = os.getenv("SECRET_KEY", "use-secure-random-key-in-production")

# === Flask Blueprint Setup ===
login_blueprint = Blueprint("login", __name__)
limiter = Limiter(get_remote_address, default_limits=[])

def get_encrypted_password() -> str:
    """
    Loads the most recent encrypted hashed credentials (deferred until needed).
    Returns the hashed_password string.
    """
    SECURE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "storage" / "backups"
    try:
        # Find all files matching pattern
        candidates = list(SECURE_PATH.glob("hashed_credentials_*.json"))
        if not candidates:
            raise FileNotFoundError("No hashed_credentials_*.json files found.")
        latest = sorted(candidates)[-1]
        return json.loads(latest.read_text(encoding="utf-8"))["hashed_password"]
    except Exception as e:
        raise RuntimeError(f"[login_web] Failed to load hashed credentials: {e}")

@limiter.limit(API_LOGIN_LIMIT)
@login_blueprint.route("/login", methods=["GET", "POST"])
def login():
    """
    POST → Decrypt stored password and compare with form input.
    GET  → Render login form.
    """
    if request.method == "POST":
        entered_password = request.form.get("password", "")
        try:
            encrypted_password = get_encrypted_password()
            decrypted_password = decrypt_password(encrypted_password)
            if entered_password == decrypted_password:
                session["authenticated"] = True
                return redirect(url_for("main.main_page"))
            else:
                return render_template("index.html", error="Invalid password")
        except Exception as e:
            return render_template("index.html", error=f"Login error: {e}")
    return render_template("index.html")

@login_blueprint.route("/logout")
def logout():
    """
    Clears session on logout.
    """
    session.pop("authenticated", None)
    return redirect(url_for("login.login"))

def login_required(f):
    """
    Route guard to enforce login session for protected views.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login.login"))
        return f(*args, **kwargs)
    return decorated_function
