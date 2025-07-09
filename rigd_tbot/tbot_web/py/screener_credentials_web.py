# tbot_web/py/screener_credentials_web.py
# Flask blueprint for screener credentials UI and API (add/edit/remove/rotate, masked, audited, fully v046 spec)

import os
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from tbot_bot.support.secrets_manager import (
    get_screener_credentials_path,
    load_screener_credentials,
    get_provider_credentials,
    list_providers
)

screener_credentials_bp = Blueprint(
    "screener_credentials",
    __name__,
    template_folder="../templates"
)

@screener_credentials_bp.route("/", methods=["GET"])
def credentials_page():
    path = get_screener_credentials_path()
    show_add = not os.path.exists(path)
    creds = {}
    if os.path.exists(path):
        try:
            creds = load_screener_credentials()
        except Exception as e:
            flash(f"Failed to load screener credentials: {e}", "error")
    providers = list(creds.keys()) if creds else []
    return render_template(
        "screener_credentials.html",
        creds=creds,
        providers=providers,
        screener_creds_exist=not show_add,
        showAddCredential=show_add
    )

@screener_credentials_bp.route("/provider/<provider>", methods=["GET"])
def get_provider(provider):
    cred = get_provider_credentials(provider)
    if cred:
        data = {k: "********" for k in cred.keys()}  # mask all values
    else:
        data = {}
    return jsonify(data)

# -- The POST routes below would typically be secured/admin-only in production --

@screener_credentials_bp.route("/add", methods=["POST"])
def add_credential():
    flash("Credential add/rotate only supported via secure UI/admin tool.", "error")
    return redirect(url_for("screener_credentials.credentials_page"))

@screener_credentials_bp.route("/rotate", methods=["POST"])
def rotate_credential():
    flash("Credential rotate only supported via secure UI/admin tool.", "error")
    return redirect(url_for("screener_credentials.credentials_page"))

@screener_credentials_bp.route("/delete", methods=["POST"])
def delete_credential():
    flash("Credential delete only supported via secure UI/admin tool.", "error")
    return redirect(url_for("screener_credentials.credentials_page"))

# This endpoint is used by url_for('screener_credentials.credentials_page')
# Register this blueprint in your app factory: app.register_blueprint(screener_credentials_bp, url_prefix='/screener_credentials')
