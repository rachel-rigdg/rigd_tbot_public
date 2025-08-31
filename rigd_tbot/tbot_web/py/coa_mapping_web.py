# tbot_web/py/coa_mapping_web.py
# Flask blueprint for COA mapping table management (no flask_login dependency).
# Provides CRUD, versioning, assignment, audit/rollback, and export/import endpoints.

import json
from functools import wraps
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app

# RBAC (same helpers used elsewhere; no flask_login)
from tbot_web.support.auth_web import get_current_user, get_user_role

# Core mapping table APIs
from tbot_bot.accounting.coa_mapping_table import (
    load_mapping_table,
    assign_mapping,
    get_mapping_for_transaction,
    flag_unmapped_transaction,
    rollback_mapping_version,
    export_mapping_table,
    import_mapping_table,
    upsert_rule,
)

# Identity / logging
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.support.utils_log import log_event

# Optional CSRF exemption (define no-op if flask_wtf isn’t installed yet)
try:
    from flask_wtf.csrf import csrf_exempt
except Exception:  # pragma: no cover
    def csrf_exempt(fn):
        return fn

coa_mapping_web = Blueprint("coa_mapping_web", __name__, template_folder="../templates")

# ---------------------------
# RBAC helpers (viewer can GET, admin required for POST mutating ops)
# ---------------------------
def _current_user_and_role():
    user = get_current_user()
    username = getattr(user, "username", None) or user or "system"
    role = get_user_role(username) if username else "viewer"
    return username, role

def admin_required(f):
    @wraps(f)
    def _wrap(*args, **kwargs):
        _user, role = _current_user_and_role()
        if role != "admin":
            if request.is_json or request.headers.get("Accept", "").startswith("application/json"):
                return jsonify({"ok": False, "error": "forbidden"}), 403
            flash("Forbidden: admin role required.", "danger")
            return redirect(url_for("coa_mapping_web.view_mapping"))
        return f(*args, **kwargs)
    return _wrap


# ---------------------------
# Pages / Views
# ---------------------------
@coa_mapping_web.route("/coa_mapping", methods=["GET"])
def view_mapping():
    """
    Render the COA mapping management page.

    Accepts optional query params:
      - from: source context (e.g., 'ledger')
      - entry_id: numeric ledger entry id for inline mapping workflows
    """
    from_source = (request.args.get("from") or "").strip() or None
    entry_id_raw = (request.args.get("entry_id") or "").strip()
    try:
        entry_id = int(entry_id_raw) if entry_id_raw else None
    except ValueError:
        entry_id = None

    mapping = load_mapping_table()
    username, role = _current_user_and_role()

    # Existing /coa/api endpoints (the UI/JS already talks to these)
    coa_api_base = "/coa/api"
    api_urls = {
        "base": coa_api_base,
        "get_mapping": f"{coa_api_base}/get_mapping",
        "assign": f"{coa_api_base}/assign",
        "versions": f"{coa_api_base}/versions",
        "rollback": f"{coa_api_base}/rollback",
        "export": f"{coa_api_base}/export",
        "import": f"{coa_api_base}/import",
        "table": f"{coa_api_base}/mapping_table",
    }

    return render_template(
        "coa_mapping.html",
        mapping=mapping,
        user=username,
        user_role=role,
        from_source=from_source,
        entry_id=entry_id,
        coa_api_base=coa_api_base,
        api_urls=api_urls,
    )


# ---------------------------
# CRUD / Assignment
# ---------------------------
@coa_mapping_web.route("/coa_mapping/assign", methods=["POST"])
@admin_required
def assign_mapping_route():
    """Assign or update a COA mapping rule via form or API (admin-only)."""
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    mapping_rule = {
        "broker": data.get("broker"),
        "type": data.get("type"),
        "subtype": data.get("subtype"),
        "description": data.get("description"),
        "coa_account": data.get("coa_account"),
    }
    reason = data.get("reason", "manual assignment")
    actor, _ = _current_user_and_role()
    assign_mapping(mapping_rule, user=actor, reason=reason)
    log_event("coa_mapping_web", f"Mapping assigned/updated by {actor}: {mapping_rule} (reason: {reason})", level="info")
    flash("Mapping assigned/updated.", "success")
    return jsonify({"success": True})


@coa_mapping_web.route("/coa_mapping/flag_unmapped", methods=["POST"])
def flag_unmapped():
    """Flag an unmapped transaction for admin review (viewer allowed to report)."""
    txn = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    actor, _ = _current_user_and_role()
    flag_unmapped_transaction(txn, user=actor)
    log_event("coa_mapping_web", f"Transaction flagged unmapped by {actor}: {txn}", level="info")
    return jsonify({"success": True})


# ---------------------------
# Versioning / Import / Export (RBAC-gated)
# ---------------------------
@coa_mapping_web.route("/coa_mapping/versions", methods=["GET"])
def list_versions():
    """List all mapping table version snapshots (viewer allowed)."""
    mapping = load_mapping_table()
    history = mapping.get("history", [])
    return jsonify(history)


@coa_mapping_web.route("/coa_mapping/rollback", methods=["POST"])
@admin_required
def rollback_mapping():
    """Rollback to a previous mapping table version (admin-only)."""
    version = int((request.form.get("version") or (request.json.get("version") if request.is_json else 0) or 0))
    actor, _ = _current_user_and_role()
    if rollback_mapping_version(version):
        log_event("coa_mapping_web", f"Mapping table rolled back to version {version} by {actor}", level="info")
        flash(f"Rolled back to mapping version {version}.", "info")
        return jsonify({"success": True})
    else:
        flash(f"Version {version} not found.", "danger")
        return jsonify({"success": False, "error": "Version not found"}), 404


@coa_mapping_web.route("/coa_mapping/export", methods=["GET"])
@admin_required
def export_mapping():
    """Download/export the current mapping table as JSON (admin-only)."""
    mapping_json = export_mapping_table()
    identity = get_bot_identity()
    filename = f"coa_mapping_table_{identity}.json"
    actor, _ = _current_user_and_role()
    log_event("coa_mapping_web", f"Mapping table exported by {actor} as {filename}", level="info")
    return current_app.response_class(
        mapping_json,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@coa_mapping_web.route("/coa_mapping/import", methods=["POST"])
@admin_required
def import_mapping():
    """Import mapping table from uploaded JSON (admin-only)."""
    if "file" not in request.files:
        flash("No file uploaded", "danger")
        return redirect(url_for("coa_mapping_web.view_mapping"))
    file = request.files["file"]
    try:
        data = file.read().decode("utf-8")
        actor, _ = _current_user_and_role()
        import_mapping_table(data, user=actor)
        log_event("coa_mapping_web", f"Mapping table imported by {actor}.", level="info")
        flash("Mapping table imported successfully.", "success")
        return redirect(url_for("coa_mapping_web.view_mapping"))
    except Exception as e:
        log_event("coa_mapping_web", f"Import failed: {e}", level="error")
        flash(f"Import failed: {e}", "danger")
        return redirect(url_for("coa_mapping_web.view_mapping"))


# ---------------------------
# Query helper
# ---------------------------
@coa_mapping_web.route("/coa_mapping/get_mapping", methods=["POST"])
def get_mapping():
    """API endpoint: fetch the mapping for a specific transaction (viewer allowed)."""
    txn = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    mapping = get_mapping_for_transaction(txn)
    return jsonify(mapping or {})


# ---------------------------
# INTERNAL helper for inline edit hook (admin-only + CSRF-exempt)
# ---------------------------
@coa_mapping_web.route("/coa_mapping/_internal/upsert_rule", methods=["POST"])
@csrf_exempt
@admin_required
def internal_upsert_rule():
    """
    CSRF-exempt internal endpoint used by inline COA edit hook.
    Body (JSON or form):
      - rule_key: str (stable key)  (optional if derived downstream)
      - account_code: str (active COA code)
      - context_meta: dict (optional; symbol/memo/broker_code/strategy/etc)
      - actor: str (optional)
    """
    data = request.get_json(silent=True) or request.form.to_dict()
    rule_key = (data.get("rule_key") or "").strip()
    account_code = (data.get("account_code") or data.get("coa_account") or "").strip()
    actor = (data.get("actor") or _current_user_and_role()[0]).strip()
    # context_meta may be JSON string via form
    cm_raw = data.get("context_meta")
    if isinstance(cm_raw, str):
        try:
            context_meta = json.loads(cm_raw)
        except Exception:
            context_meta = {"raw": cm_raw}
    else:
        context_meta = cm_raw or {}

    if not account_code:
        return jsonify({"ok": False, "error": "missing account_code"}), 400

    try:
        version_id = upsert_rule(rule_key=rule_key, account_code=account_code, context_meta=context_meta, actor=actor)
        log_event("coa_mapping_web", f"internal upsert_rule by {actor}: rule_key={rule_key}, account_code={account_code}", level="info")
        return jsonify({"ok": True, "version_id": version_id})
    except Exception as e:
        log_event("coa_mapping_web", f"internal upsert_rule failed: {e}", level="error")
        return jsonify({"ok": False, "error": str(e)}), 500
