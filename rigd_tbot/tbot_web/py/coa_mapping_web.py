# tbot_web/py/coa_mapping_web.py
# Flask blueprint for COA mapping table management.
# Provides full CRUD, versioning, assignment, audit/rollback, and export/import endpoints as per specification.

import os
import json
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app, send_file
from flask_login import login_required, current_user
from tbot_bot.accounting.coa_mapping_table import (
    load_mapping_table, assign_mapping, get_mapping_for_transaction,
    flag_unmapped_transaction, rollback_mapping_version,
    export_mapping_table, import_mapping_table
)
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.support.utils_log import log_event

coa_mapping_web = Blueprint("coa_mapping_web", __name__, template_folder="../templates")

@coa_mapping_web.route("/coa_mapping", methods=["GET"])
@login_required
def view_mapping():
    """Render the COA mapping management page."""
    mapping = load_mapping_table()
    return render_template("coa_mapping.html", mapping=mapping, user=current_user)

@coa_mapping_web.route("/coa_mapping/assign", methods=["POST"])
@login_required
def assign_mapping_route():
    """Assign or update a COA mapping rule via form or API."""
    data = request.get_json() if request.is_json else request.form.to_dict()
    mapping_rule = {
        "broker": data.get("broker"),
        "type": data.get("type"),
        "subtype": data.get("subtype"),
        "description": data.get("description"),
        "coa_account": data.get("coa_account")
    }
    reason = data.get("reason", "manual assignment")
    assign_mapping(mapping_rule, user=current_user.username, reason=reason)
    log_event(
        "coa_mapping_web",
        f"Mapping assigned/updated by {current_user.username}: {mapping_rule} (reason: {reason})",
        level="info"
    )
    flash("Mapping assigned/updated.", "success")
    return jsonify({"success": True})

@coa_mapping_web.route("/coa_mapping/flag_unmapped", methods=["POST"])
@login_required
def flag_unmapped():
    """Flag an unmapped transaction for admin review."""
    txn = request.get_json() if request.is_json else request.form.to_dict()
    flag_unmapped_transaction(txn, user=current_user.username)
    log_event(
        "coa_mapping_web",
        f"Transaction flagged unmapped by {current_user.username}: {txn}",
        level="info"
    )
    return jsonify({"success": True})

@coa_mapping_web.route("/coa_mapping/rollback", methods=["POST"])
@login_required
def rollback_mapping():
    """Rollback to a previous mapping table version."""
    version = int(request.form.get("version", 0) or 0)
    if rollback_mapping_version(version):
        log_event(
            "coa_mapping_web",
            f"Mapping table rolled back to version {version} by {current_user.username}",
            level="info"
        )
        flash(f"Rolled back to mapping version {version}.", "info")
        return jsonify({"success": True})
    else:
        flash(f"Version {version} not found.", "danger")
        return jsonify({"success": False, "error": "Version not found"})

@coa_mapping_web.route("/coa_mapping/export", methods=["GET"])
@login_required
def export_mapping():
    """Download/export the current mapping table as JSON."""
    mapping_json = export_mapping_table()
    identity = get_bot_identity()
    filename = f"coa_mapping_table_{identity}.json"
    log_event(
        "coa_mapping_web",
        f"Mapping table exported by {current_user.username} as {filename}",
        level="info"
    )
    return current_app.response_class(
        mapping_json,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@coa_mapping_web.route("/coa_mapping/import", methods=["POST"])
@login_required
def import_mapping():
    """Import mapping table from uploaded JSON."""
    if "file" not in request.files:
        flash("No file uploaded", "danger")
        return redirect(url_for("coa_mapping_web.view_mapping"))
    file = request.files["file"]
    try:
        data = file.read().decode("utf-8")
        import_mapping_table(data, user=current_user.username)
        log_event(
            "coa_mapping_web",
            f"Mapping table imported by {current_user.username}.",
            level="info"
        )
        flash("Mapping table imported successfully.", "success")
    except Exception as e:
        flash(f"Import failed: {e}", "danger")
    return redirect(url_for("coa_mapping_web.view_mapping"))

@coa_mapping_web.route("/coa_mapping/get_mapping", methods=["POST"])
@login_required
def get_mapping():
    """API endpoint: fetch the mapping for a specific transaction."""
    txn = request.get_json() if request.is_json else request.form.to_dict()
    mapping = get_mapping_for_transaction(txn)
    return jsonify(mapping or {})

@coa_mapping_web.route("/coa_mapping/versions", methods=["GET"])
@login_required
def list_versions():
    """List all mapping table version snapshots (for rollback or audit)."""
    mapping = load_mapping_table()
    history = mapping.get("history", [])
    return jsonify(history)
