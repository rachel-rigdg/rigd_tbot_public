# tbot_web/py/coa_mapping_web.py
# Flask blueprint for COA mapping table management.
# Uses tbot_bot.accounting.coa_mapping_table for append-only, versioned CRUD.

from __future__ import annotations

import json
from flask import (
    Blueprint, render_template, request, jsonify, redirect,
    url_for, flash, current_app
)

# Use app's RBAC utilities instead of flask_login
from tbot_web.support.auth_web import rbac_required, get_current_user

from tbot_bot.accounting.coa_mapping_table import (
    load_mapping_table,
    assign_mapping,
    get_mapping_for_transaction,
    flag_unmapped_transaction,
    rollback_mapping_version,
    export_mapping_table,
    import_mapping_table,
    get_version,
)
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.support.utils_log import log_event

coa_mapping_web = Blueprint("coa_mapping_web", __name__, template_folder="../templates")


# -----------------
# Helpers
# -----------------

def _normalize_incoming(data: dict) -> dict:
    """Support both form and JSON payloads; accept legacy keys gracefully."""
    # Canonical match keys
    match = {
        "broker": (data.get("broker") or "").strip() or None,
        "type": (data.get("type") or "").strip() or None,
        "subtype": (data.get("subtype") or "").strip() or None,
        "description": (data.get("description") or "").strip() or None,
    }
    # Drop empty
    match = {k: v for k, v in match.items() if v}

    # Account sides: prefer explicit debit/credit; fallback to legacy 'coa_account' if given
    debit_account = (data.get("debit_account") or "").strip()
    credit_account = (data.get("credit_account") or "").strip()
    legacy_single = (data.get("coa_account") or "").strip()

    if not debit_account and legacy_single:
        debit_account = legacy_single
    if not credit_account and legacy_single:
        credit_account = legacy_single

    code = (data.get("code") or "").strip() or None
    reason = (data.get("reason") or "manual assignment").strip()

    return {
        "match": match,
        "debit_account": debit_account,
        "credit_account": credit_account,
        "code": code,
        "reason": reason,
    }


def _validate_mapping_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    if not payload["debit_account"]:
        errors.append("Missing debit_account.")
    if not payload["credit_account"]:
        errors.append("Missing credit_account.")
    # Optional: basic sanity (avoid Uncategorized defaults from slipping through UI)
    if payload["debit_account"].lower().startswith("uncategorized"):
        errors.append("debit_account cannot be 'Uncategorized'.")
    if payload["credit_account"].lower().startswith("uncategorized"):
        errors.append("credit_account cannot be 'Uncategorized'.")
    # At least one discriminator or explicit code recommended
    if not payload["code"] and not payload["match"]:
        errors.append("Provide at least one match field (broker/type/subtype/description) or an explicit code.")
    return errors


def _username() -> str:
    u = get_current_user()
    return getattr(u, "username", None) or (str(u) if u else "anonymous")


# -----------------
# Views
# -----------------

@coa_mapping_web.route("/coa_mapping", methods=["GET"])
@rbac_required()  # viewer/trader/admin may view
def view_mapping():
    """Render the COA mapping management page."""
    mapping = load_mapping_table()
    current_ver = int(mapping.get("meta", {}).get("version_id", mapping.get("version", 1)))
    return render_template("coa_mapping.html", mapping=mapping, user=get_current_user(), version=current_ver)


# -----------------
# CRUD (append-only via assign)
# -----------------

@coa_mapping_web.route("/coa_mapping/assign", methods=["POST"])
@rbac_required(role="admin")  # restrict writes to admin
def assign_mapping_route():
    """
    Assign or update a COA mapping rule.
    Required: debit_account, credit_account
    Optional match keys: broker, type, subtype, description
    Optional: code (deterministic if omitted), reason
    """
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    payload = _normalize_incoming(data)
    errors = _validate_mapping_payload(payload)
    if errors:
        msg = " ".join(errors)
        flash(msg, "danger")
        return jsonify({"success": False, "error": msg}), 400

    # Construct assign_mapping input
    mapping_rule = {
        "debit_account": payload["debit_account"],
        "credit_account": payload["credit_account"],
        "code": payload["code"],
        # flatten match keys into top-level for assign_mapping()
        **payload["match"],
    }

    try:
        before_ver = get_version()
        table = assign_mapping(mapping_rule, user=_username(), reason=payload["reason"])
        after_ver = int(table.get("meta", {}).get("version_id", table.get("version", before_ver)))
        # Surface outcome
        log_event(
            "coa_mapping_web",
            f"Mapping assigned by {_username()}: {json.dumps(mapping_rule, ensure_ascii=False)} (reason: {payload['reason']}) -> v{after_ver}",
            level="info",
        )
        flash(f"Mapping saved. Version bumped to v{after_ver}.", "success")
        return jsonify({"success": True, "version": after_ver})
    except Exception as e:
        log_event("coa_mapping_web", f"Assign failed for {_username()}: {e}", level="error")
        flash(f"Assign failed: {e}", "danger")
        return jsonify({"success": False, "error": str(e)}), 500


@coa_mapping_web.route("/coa_mapping/flag_unmapped", methods=["POST"])
@rbac_required()  # any role can flag for review
def flag_unmapped():
    """Flag an unmapped transaction for admin review."""
    txn = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    try:
        flag_unmapped_transaction(txn, user=_username())
        log_event("coa_mapping_web", f"Unmapped txn flagged by {_username()}: {txn}", level="info")
        flash("Transaction flagged for review.", "info")
        return jsonify({"success": True})
    except Exception as e:
        log_event("coa_mapping_web", f"Flag unmapped failed: {e}", level="error")
        flash(f"Failed to flag transaction: {e}", "danger")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------
# Versioning
# -----------------

@coa_mapping_web.route("/coa_mapping/rollback", methods=["POST"])
@rbac_required(role="admin")
def rollback_mapping():
    """Rollback to a previous mapping table version (creates a new version that equals the snapshot)."""
    try:
        version = int(request.form.get("version", "0") or "0")
    except Exception:
        flash("Invalid version number.", "danger")
        return jsonify({"success": False, "error": "invalid_version"}), 400

    try:
        ok = rollback_mapping_version(version)
        if ok:
            new_ver = get_version()
            log_event("coa_mapping_web", f"Rolled back to v{version} (now current v{new_ver}) by {_username()}", level="info")
            flash(f"Rolled back to snapshot v{version}. Current version is now v{new_ver}.", "info")
            return jsonify({"success": True, "version": new_ver})
        flash(f"Version v{version} not found.", "danger")
        return jsonify({"success": False, "error": "version_not_found"}), 404
    except Exception as e:
        log_event("coa_mapping_web", f"Rollback failed: {e}", level="error")
        flash(f"Rollback failed: {e}", "danger")
        return jsonify({"success": False, "error": str(e)}), 500


@coa_mapping_web.route("/coa_mapping/versions", methods=["GET"])
@rbac_required()
def list_versions():
    """List version snapshots with minimal metadata."""
    mapping = load_mapping_table()
    history = mapping.get("history", [])
    current_ver = int(mapping.get("meta", {}).get("version_id", mapping.get("version", 1)))
    return jsonify({"history": history, "current_version": current_ver})


# -----------------
# Export / Import
# -----------------

@coa_mapping_web.route("/coa_mapping/export", methods=["GET"])
@rbac_required()  # export allowed for all roles
def export_mapping():
    """Download/export the current mapping table as JSON (append-only snapshots live on disk)."""
    mapping_json = export_mapping_table()
    identity = get_bot_identity()
    filename = f"coa_mapping_table_{identity}.json"
    log_event("coa_mapping_web", f"Mapping exported by {_username()} as {filename}", level="info")
    return current_app.response_class(
        mapping_json,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@coa_mapping_web.route("/coa_mapping/import", methods=["POST"])
@rbac_required(role="admin")
def import_mapping():
    """
    Import a full mapping table JSON.
    Append-only semantics: provider writes a new version snapshot.
    """
    if "file" not in request.files:
        flash("No file uploaded.", "danger")
        return redirect(url_for("coa_mapping_web.view_mapping"))

    file = request.files["file"]
    try:
        data = file.read().decode("utf-8")
        import_mapping_table(data, user=_username())
        ver = get_version()
        log_event("coa_mapping_web", f"Mapping imported by {_username()} -> v{ver}", level="info")
        flash(f"Mapping imported successfully (current version v{ver}).", "success")
    except Exception as e:
        log_event("coa_mapping_web", f"Import failed: {e}", level="error")
        flash(f"Import failed: {e}", "danger")
    return redirect(url_for("coa_mapping_web.view_mapping"))


# -----------------
# Lookup / Test
# -----------------

@coa_mapping_web.route("/coa_mapping/get_mapping", methods=["POST"])
@rbac_required()
def get_mapping():
    """
    API: fetch the active mapping row for a transaction dict.
    Accepts JSON or form fields containing broker/type/subtype/description or code.
    """
    txn = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    try:
        mapping = get_mapping_for_transaction(txn)
        return jsonify(mapping or {})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
