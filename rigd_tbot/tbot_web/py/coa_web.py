# tbot_web/py/coa_web.py
# Dedicated page and API endpoints for human-readable COA viewing/editing via Web UI

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, send_file, flash
from datetime import datetime, timezone
import json
import io

from tbot_web.support.auth_web import rbac_required
from tbot_web.support.utils_coa_web import (
    load_coa_metadata_and_accounts,
    save_coa_json,
    export_coa_markdown,
    export_coa_csv,
    get_coa_audit_log,
    compute_coa_diff,
    validate_coa_json,
)
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import validate_bot_identity, get_bot_identity_string_regex

coa_web = Blueprint("coa_web", __name__, template_folder="../templates")

def utcnow():
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def identity_guard():
    try:
        bot_identity_string = load_bot_identity()
        if not bot_identity_string or not get_bot_identity_string_regex().match(bot_identity_string):
            flash("Bot identity not available, please complete configuration.")
            return True
        validate_bot_identity(bot_identity_string)
        return False
    except Exception:
        flash("Bot identity not available, please complete configuration.")
        return True

# --- COA Management Page ---
@coa_web.route("/coa", methods=["GET"])
@rbac_required()
def coa_management():
    print("[DEBUG] session:", dict(session))  # <--- Add this line
    user = session.get("user", "unknown")
    user_is_admin = session.get("role", "") == "admin"
    if identity_guard():
        return render_template(
            "coa.html",
            user_is_admin=user_is_admin,
            coa_json=None,
            error="Bot identity not available, please complete configuration."
        )
    try:
        coa_data = load_coa_metadata_and_accounts()
        coa_json = json.dumps(coa_data.get('accounts', []), indent=2)
        return render_template(
            "coa.html",
            user_is_admin=user_is_admin,
            coa_json=coa_json,
            error=None
        )
    except FileNotFoundError:
        return render_template(
            "coa.html",
            user_is_admin=user_is_admin,
            coa_json=None,
            error="COA or metadata file not found. Please initialize via admin tools."
        )
    except Exception as e:
        return render_template(
            "coa.html",
            user_is_admin=user_is_admin,
            coa_json=None,
            error=f"COA error: {e}"
        )

# --- COA API: metadata, hierarchy, audit log (JSON) ---
@coa_web.route("/coa/api", methods=["GET"])
@rbac_required()
def coa_api():
    if identity_guard():
        return jsonify({"error": "Bot identity not available, please complete configuration."}), 400
    try:
        coa_data = load_coa_metadata_and_accounts()
        metadata = coa_data.get("metadata", {})
        accounts = coa_data.get("accounts", [])
        audit_history = get_coa_audit_log(limit=50)
        return jsonify({
            "metadata": metadata,
            "accounts": accounts,
            "history": audit_history
        })
    except FileNotFoundError:
        return jsonify({"error": "COA or metadata file not found. Please initialize via admin tools."}), 400
    except Exception as e:
        return jsonify({"error": f"COA error: {e}"}), 400

# --- COA Edit (Admin Only) ---
@coa_web.route("/coa/edit", methods=["POST"])
@rbac_required(role="admin")
def coa_edit():
    if identity_guard():
        return "Bot identity not available, please complete configuration.", 400
    raw_json = request.form.get("coa_json", "")
    user = session.get("user", "unknown")
    try:
        new_accounts = json.loads(raw_json)
        validate_coa_json(new_accounts)
        old_data = load_coa_metadata_and_accounts()
        diff = compute_coa_diff(old_data.get('accounts', []), new_accounts)
        save_coa_json(new_accounts, user=user, diff=diff)
        return redirect(url_for("coa_web.coa_management"))
    except Exception as e:
        return f"Error updating COA: {str(e)}", 400

# --- Export: Markdown ---
@coa_web.route("/coa/export/markdown", methods=["GET"])
@rbac_required()
def coa_export_markdown():
    if identity_guard():
        return "Bot identity not available, please complete configuration.", 400
    try:
        coa_data = load_coa_metadata_and_accounts()
        md = export_coa_markdown(coa_data)
        buf = io.BytesIO(md.encode('utf-8'))
        ts = utcnow().strftime("%Y%m%dT%H%M%SZ")
        filename = f"COA_{coa_data.get('metadata', {}).get('entity_code','')}_{ts}.md"
        return send_file(buf, mimetype="text/markdown", as_attachment=True, download_name=filename)
    except FileNotFoundError:
        return "COA or metadata file not found. Please initialize via admin tools.", 400
    except Exception as e:
        return f"COA error: {e}", 400

# --- Export: CSV ---
@coa_web.route("/coa/export/csv", methods=["GET"])
@rbac_required()
def coa_export_csv():
    if identity_guard():
        return "Bot identity not available, please complete configuration.", 400
    try:
        coa_data = load_coa_metadata_and_accounts()
        csv_txt = export_coa_csv(coa_data)
        buf = io.BytesIO(csv_txt.encode('utf-8'))
        ts = utcnow().strftime("%Y%m%dT%H%M%SZ")
        filename = f"COA_{coa_data.get('metadata', {}).get('entity_code','')}_{ts}.csv"
        return send_file(buf, mimetype="text/csv", as_attachment=True, download_name=filename)
    except FileNotFoundError:
        return "COA or metadata file not found. Please initialize via admin tools.", 400
    except Exception as e:
        return f"COA error: {e}", 400

# --- RBAC API: (for JS/Frontend/CI Testing) ---
@coa_web.route("/coa/rbac", methods=["GET"])
def coa_rbac_status():
    user_is_admin = session.get("role", "") == "admin"
    return jsonify({"user_is_admin": user_is_admin})
