# tbot_web/support/csrf_protection.py
# Implements CSRF protection middleware for Flask

import secrets
from flask import request, session, abort

CSRF_TOKEN_KEY = "_csrf_token"

def generate_csrf_token():
    """
    Generate a new CSRF token and store it in the session.
    """
    if CSRF_TOKEN_KEY not in session:
        session[CSRF_TOKEN_KEY] = secrets.token_urlsafe(32)
    return session[CSRF_TOKEN_KEY]

def validate_csrf_token():
    """
    Validate CSRF token sent in the request against the session token.
    Aborts request with 400 if tokens do not match or missing.
    """
    token = None

    # Token may be sent in form data, JSON body, or headers
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        # Check form data
        token = request.form.get(CSRF_TOKEN_KEY)
        if not token and request.is_json:
            json_data = request.get_json(silent=True)
            if json_data:
                token = json_data.get(CSRF_TOKEN_KEY)
        if not token:
            token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")

    session_token = session.get(CSRF_TOKEN_KEY, None)

    if not token or not session_token or token != session_token:
        abort(400, description="Invalid or missing CSRF token.")

def csrf_protect(app):
    """
    Attach CSRF protection to the Flask app.
    - Generates token per session
    - Validates token on unsafe HTTP methods
    """

    @app.before_request
    def check_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            validate_csrf_token()

    # Provide function in template context to insert token in forms
    app.jinja_env.globals["csrf_token"] = generate_csrf_token
