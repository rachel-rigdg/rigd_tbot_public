# tbot_web/py/coa_web.py
#  Dedicated page and API endpoints for human-readable COA viewing/editing via Web UI

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, send_file
from flask import current_app as app
from datetime import datetime, timezone
import json
import os
import io

from tbot_web.support.auth_web import rbac_required  # Corrected absolute import per directory spec
from tbot_bot.support.utils_coa_web import (        # Corrected absolute import per directory spec
    load_coa_metadata_and_accounts,
    save_coa_json,
    export_coa_markdown,
    export_coa_csv,
    get_coa_audit_log,
    compute_coa_diff,
    validate_coa_json,
)

coa_web = Blueprint("coa_web", __name__, template_folder="../templates")

def utcnow():
    return datetime.utcnow().replace(tzinfo=timezone.utc)

# --- COA Management Page ---
@coa_web.route("/coa", methods=["GET"])
@rbac_required()
def coa_management():
    user = session.get("user", "unknown")
    user_is_admin = session.get("role", "") == "admin"
    coa_data = load_coa_metadata_and_accounts()
    coa_json = json.dumps(coa_data['accounts'], indent=2)
    return render_template(
        "coa.html",
        user_is_admin=user_is_admin,
        coa_json=coa_json,
    )

# --- COA API: metadata, hierarchy, audit log (JSON) ---
@coa_web.route("/coa/api", methods=["GET"])
@rbac_required()
def coa_api():
    coa_data = load_coa_metadata_and_accounts()
    audit_history = get_coa_audit_log(limit=50)
    return jsonify({
        "metadata": coa_data["metadata"],
        "accounts": coa_data["accounts"],
        "history": audit_history
    })

# --- COA Edit (Admin Only) ---
@coa_web.route("/coa/edit", methods=["POST"])
@rbac_required(role="admin")
def coa_edit():
    raw_json = request.form.get("coa_json", "")
    user = session.get("user", "unknown")
    try:
        new_accounts = json.loads(raw_json)
        validate_coa_json(new_accounts)
        old_data = load_coa_metadata_and_accounts()
        diff = compute_coa_diff(old_data['accounts'], new_accounts)
        save_coa_json(new_accounts, user=user, diff=diff)
        return redirect(url_for("coa_web.coa_management"))
    except Exception as e:
        return f"Error updating COA: {str(e)}", 400

# --- Export: Markdown ---
@coa_web.route("/coa/export/markdown", methods=["GET"])
@rbac_required()
def coa_export_markdown():
    coa_data = load_coa_metadata_and_accounts()
    md = export_coa_markdown(coa_data)
    buf = io.BytesIO(md.encode('utf-8'))
    ts = utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"COA_{coa_data['metadata']['entity_code']}_{ts}.md"
    return send_file(buf, mimetype="text/markdown", as_attachment=True, download_name=filename)

# --- Export: CSV ---
@coa_web.route("/coa/export/csv", methods=["GET"])
@rbac_required()
def coa_export_csv():
    coa_data = load_coa_metadata_and_accounts()
    csv_txt = export_coa_csv(coa_data)
    buf = io.BytesIO(csv_txt.encode('utf-8'))
    ts = utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = f"COA_{coa_data['metadata']['entity_code']}_{ts}.csv"
    return send_file(buf, mimetype="text/csv", as_attachment=True, download_name=filename)

# --- RBAC API: (for JS/Frontend/CI Testing) ---
@coa_web.route("/coa/rbac", methods=["GET"])
def coa_rbac_status():
    user_is_admin = session.get("role", "") == "admin"
    return jsonify({"user_is_admin": user_is_admin})
