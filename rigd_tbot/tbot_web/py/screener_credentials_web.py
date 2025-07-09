# tbot_web/py/screener_credentials_web.py
# Flask blueprint for screener credentials UI and API (add/edit/remove/rotate, masked, audited, fully v046 spec)

import os
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from tbot_bot.support.secrets_manager import (
    get_screener_credentials_path,
    load_screener_credentials,
    get_provider_credentials,
    save_screener_credentials,
    delete_provider_credentials,
    list_providers
)

screener_credentials_bp = Blueprint(
    "screener_credentials",
    __name__,
    template_folder="../templates"
)

SCREENER_KEYS = [
    "SCREENER_NAME",
    "SCREENER_USERNAME",
    "SCREENER_PASSWORD",
    "SCREENER_URL",
    "SCREENER_API_KEY",
    "SCREENER_TOKEN"
]

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
        showAddCredential=show_add,
        screener_keys=SCREENER_KEYS
    )

@screener_credentials_bp.route("/provider/<provider>", methods=["GET"])
def get_provider(provider):
    cred = get_provider_credentials(provider)
    if cred:
        data = {k: "********" for k in cred.keys()}  # mask all values
    else:
        data = {}
    return jsonify(data)

@screener_credentials_bp.route("/add", methods=["POST"])
def add_credential():
    provider = request.form.get("provider", "").strip().upper()
    values = {}
    for key in SCREENER_KEYS:
        val = request.form.get(key, "").strip()
        if val:
            values[key] = val
    if not provider or not values:
        flash("Provider name and at least one credential field are required.", "error")
        return redirect(url_for("screener_credentials.credentials_page"))
    try:
        creds = load_screener_credentials() if os.path.exists(get_screener_credentials_path()) else {}
        if provider in creds:
            flash(f"Provider {provider} already exists. Use Edit to update.", "error")
            return redirect(url_for("screener_credentials.credentials_page"))
        creds[provider] = values
        save_screener_credentials(creds)
        flash(f"Added credentials for {provider}", "success")
    except Exception as e:
        flash(f"Failed to add credentials: {e}", "error")
    return redirect(url_for("screener_credentials.credentials_page"))

@screener_credentials_bp.route("/update", methods=["POST"])
def update_credential():
    provider = request.form.get("provider", "").strip().upper()
    values = {}
    for key in SCREENER_KEYS:
        val = request.form.get(key, "").strip()
        if val:
            values[key] = val
    if not provider or not values:
        flash("Provider name and at least one credential field are required.", "error")
        return redirect(url_for("screener_credentials.credentials_page"))
    try:
        creds = load_screener_credentials()
        if provider not in creds:
            flash(f"Provider {provider} does not exist. Use Add to create.", "error")
            return redirect(url_for("screener_credentials.credentials_page"))
        creds[provider] = values
        save_screener_credentials(creds)
        flash(f"Updated credentials for {provider}", "success")
    except Exception as e:
        flash(f"Failed to update credentials: {e}", "error")
    return redirect(url_for("screener_credentials.credentials_page"))

@screener_credentials_bp.route("/rotate", methods=["POST"])
def rotate_credential():
    provider = request.form.get("provider", "").strip().upper()
    new_key = request.form.get("new_key", "").strip()
    new_value = request.form.get("new_value", "").strip()
    if not provider or not new_key or not new_value:
        flash("Provider and new key/value are required for rotation.", "error")
        return redirect(url_for("screener_credentials.credentials_page"))
    try:
        creds = load_screener_credentials()
        if provider not in creds:
            flash(f"Provider {provider} not found.", "error")
            return redirect(url_for("screener_credentials.credentials_page"))
        creds[provider][new_key] = new_value
        save_screener_credentials(creds)
        flash(f"Rotated credential for {provider}: {new_key}", "success")
    except Exception as e:
        flash(f"Failed to rotate credential: {e}", "error")
    return redirect(url_for("screener_credentials.credentials_page"))

@screener_credentials_bp.route("/delete", methods=["POST"])
def delete_credential():
    provider = request.form.get("provider", "").strip().upper()
    if not provider:
        flash("Provider name required.", "error")
        return redirect(url_for("screener_credentials.credentials_page"))
    try:
        delete_provider_credentials(provider)
        flash(f"Deleted credentials for {provider}", "success")
    except Exception as e:
        flash(f"Failed to delete credentials: {e}", "error")
    return redirect(url_for("screener_credentials.credentials_page"))
