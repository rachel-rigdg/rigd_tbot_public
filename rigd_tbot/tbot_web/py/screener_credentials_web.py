# tbot_web/py/screener_credentials_web.py
# Surgical fix to ensure screener_api.json.enc is always saved as nested dict keyed by provider.

import os
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from tbot_bot.support.secrets_manager import (
    get_screener_credentials_path,
    load_screener_credentials,
    get_provider_credentials,
    save_screener_credentials,
    update_provider_credentials,
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
            # Fix: if creds is flat dict (has SCREENER_NAME key), convert to nested dict
            if any(k.startswith("SCREENER_") for k in creds.keys()):
                creds = {"DEFAULT": creds}
                save_screener_credentials(creds)
        except Exception as e:
            flash(f"Failed to load screener credentials: {e}", "error")
    providers = list(creds.keys()) if creds else []
    creds_json = json.dumps(creds)
    return render_template(
        "screener_credentials.html",
        creds=creds,
        providers=providers,
        screener_creds_exist=not show_add,
        showAddCredential=show_add,
        screener_keys=SCREENER_KEYS,
        creds_json=creds_json,
        keys_json=json.dumps(SCREENER_KEYS)
    )

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
        # Ensure creds is nested dict keyed by provider
        if any(k.startswith("SCREENER_") for k in creds.keys()):
            creds = {"DEFAULT": creds}
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
        if any(k.startswith("SCREENER_") for k in creds.keys()):
            creds = {"DEFAULT": creds}
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
        if any(k.startswith("SCREENER_") for k in creds.keys()):
            creds = {"DEFAULT": creds}
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
        creds = load_screener_credentials()
        if any(k.startswith("SCREENER_") for k in creds.keys()):
            creds = {"DEFAULT": creds}
        if provider in creds:
            del creds[provider]
            save_screener_credentials(creds)
            flash(f"Deleted credentials for {provider}", "success")
        else:
            flash(f"Provider {provider} not found.", "error")
    except Exception as e:
        flash(f"Failed to delete credentials: {e}", "error")
    return redirect(url_for("screener_credentials.credentials_page"))
