# tbot_web/py/screener_credentials_web.py
# Updated for generic indexed credential management with explicit provider indexing and always writing to file

import os
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from tbot_bot.support.secrets_manager import (
    get_screener_credentials_path,
    load_screener_credentials,
    get_provider_credentials,
    save_screener_credentials,
    update_provider_credentials,
    delete_provider_credentials,
    list_providers
)
import re

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

def unpack_credentials(creds: dict) -> dict:
    providers = {}
    provider_indices = {}
    for k, v in creds.items():
        m = re.match(r'^PROVIDER_(\d{2})$', k)
        if m:
            provider_indices[m.group(1)] = v.upper()
    for idx, pname in provider_indices.items():
        providers[pname] = {}
        for k, v in creds.items():
            if k.endswith(f"_{idx}") and not k.startswith("PROVIDER_"):
                base_key = k.rsplit("_", 1)[0]
                providers[pname][base_key] = v
    return providers

@screener_credentials_bp.route("/", methods=["GET"])
def credentials_page():
    path = get_screener_credentials_path()
    show_add = not os.path.exists(path)
    creds = {}
    providers = []
    if os.path.exists(path):
        try:
            raw_creds = load_screener_credentials()
            creds = unpack_credentials(raw_creds)
            providers = list(creds.keys())
        except Exception as e:
            flash(f"Failed to load screener credentials: {e}", "error")
    creds_json = json.dumps(creds)
    keys_json = json.dumps(SCREENER_KEYS)
    return render_template(
        "screener_credentials.html",
        creds=creds,
        providers=providers,
        screener_creds_exist=not show_add,
        showAddCredential=show_add,
        screener_keys=SCREENER_KEYS,
        creds_json=creds_json,
        keys_json=keys_json
    )

@screener_credentials_bp.route("/provider/<provider>", methods=["GET"])
def get_provider(provider):
    cred = get_provider_credentials(provider)
    if cred:
        data = {k: "********" for k in cred.keys()}
    else:
        data = {}
    return jsonify(data)

@screener_credentials_bp.route("/add", methods=["POST"])
def add_credential():
    provider = request.form.get("provider", "").strip().upper()
    if not provider:
        flash("Provider name is required.", "error")
        return redirect(url_for("screener_credentials.credentials_page"))
    values = {}
    for key in SCREENER_KEYS:
        val = request.form.get(key, "").strip()
        if val:
            values[key] = val
    if not values:
        flash("At least one credential field is required.", "error")
        return redirect(url_for("screener_credentials.credentials_page"))
    try:
        creds = load_screener_credentials() if os.path.exists(get_screener_credentials_path()) else {}
        unpacked_creds = unpack_credentials(creds)
        if provider in unpacked_creds:
            flash(f"Provider {provider} already exists. Use Edit to update.", "error")
            return redirect(url_for("screener_credentials.credentials_page"))
        update_provider_credentials(provider, values)
        flash(f"Added credentials for {provider}", "success")
    except Exception as e:
        flash(f"Failed to add credentials: {e}", "error")
    return redirect(url_for("screener_credentials.credentials_page"))

@screener_credentials_bp.route("/update", methods=["POST"])
def update_credential():
    provider = request.form.get("provider", "").strip().upper()
    if not provider:
        flash("Provider name is required.", "error")
        return redirect(url_for("screener_credentials.credentials_page"))
    values = {}
    for key in SCREENER_KEYS:
        val = request.form.get(key, "").strip()
        if val:
            values[key] = val
    if not values:
        flash("At least one credential field is required.", "error")
        return redirect(url_for("screener_credentials.credentials_page"))
    try:
        update_provider_credentials(provider, values)
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
        unpacked_creds = unpack_credentials(creds)
        if provider not in unpacked_creds:
            flash(f"Provider {provider} not found.", "error")
            return redirect(url_for("screener_credentials.credentials_page"))
        index = None
        for k, v in creds.items():
            if re.match(r"PROVIDER_\d{2}", k) and v.strip().upper() == provider:
                index = k.split("_")[-1]
                break
        if not index:
            flash(f"Provider index for {provider} not found.", "error")
            return redirect(url_for("screener_credentials.credentials_page"))
        creds[f"{new_key}_{index}"] = new_value
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
