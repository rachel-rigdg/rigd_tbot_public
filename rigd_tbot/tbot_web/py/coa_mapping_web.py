# tbot_web/py/coa_mapping_web.py
# Flask blueprint for COA mapping table management (no flask_login dependency).
# Provides CRUD, versioning, assignment, audit/rollback, and export/import endpoints.

import json
from functools import wraps
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app

# RBAC helpers (no flask_login)
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
from tbot_bot.accounting.reconciliation_log import log_event_coa_mapping_updated  # AUDIT (event_type enforced)

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
# Shape/flatten utilities
# ---------------------------
_EXPECTED_KEYS = (
    "broker", "type", "subtype", "description",
    "debit_account", "credit_account", "coa_account",
    "updated_at", "updated_by", "rule_key", "source"
)

def _normalize_row(d: dict, *, source: str = "") -> dict:
    """Ensure a consistent row shape for the UI (legacy mapping OR programmatic rule)."""
    if not isinstance(d, dict):
        return {"raw": d, "source": source}
    out = dict(d)
    out["source"] = source or out.get("source") or ("rule" if "rule_key" in out else "mapping")

    # If only a single account is present, map to coa_account and present as 'debit' for UI table
    if "coa_account" not in out:
        for k in ("account", "account_code"):
            if k in out and out[k] and not out.get("debit_account") and not out.get("credit_account"):
                out["coa_account"] = out.get(k)
                break

    # Guarantee presence of all keys (None if missing)
    for k in _EXPECTED_KEYS:
        out.setdefault(k, None)
    return out


def _flatten_mapping_table(doc) -> list:
    """
    Accepts any of:
      - {"mappings":[...]} legacy field-based rules
      - {"rules":[...]} programmatic seeded rules OR dict of {rule_key: {...}|<account>}
      - list[...] fallbacks
    Returns a list of dict rows normalized for UI.
    """
    rows = []
    if isinstance(doc, dict):
        # Programmatic rules first so seeded defaults are visible up top
        if isinstance(doc.get("rules"), list):
            rows.extend(_normalize_row(r, source="rule") for r in doc["rules"])
        elif isinstance(doc.get("rules"), dict):
            for rk, val in doc["rules"].items():
                if isinstance(val, dict):
                    r = {"rule_key": rk, **val}
                else:
                    r = {"rule_key": rk, "coa_account": val}
                rows.append(_normalize_row(r, source="rule"))

        # Legacy field-based mappings (if any)
        if isinstance(doc.get("mappings"), list):
            rows.extend(_normalize_row(r, source="mapping") for r in doc["mappings"])
    elif isinstance(doc, list):
        rows = [_normalize_row(r) for r in doc]
    else:
        rows = []

    return rows


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

    # Load mapping JSON; auto-seeded defaults (if your coa_mapping_table implements seeding).
    raw_mapping = load_mapping_table() or {}
    normalized_rows = _flatten_mapping_table(raw_mapping)

    # Flag for template banners / hints (optional use)
    has_seeded_rules = any(r for r in normalized_rows if r.get("source") == "rule")

    # Build mapping_rows in the shape current template expects
    mapping_rows = []
    for r in normalized_rows:
        broker = (r.get("broker") or "").strip()
        typ = (r.get("type") or "").strip()
        sub = (r.get("subtype") or "").strip()
        desc = (r.get("description") or "").strip()
        # For programmatic rules, show single-account rule under 'debit_account' for the existing UI table
        debit = (r.get("debit_account") or r.get("coa_account") or "").strip()
        credit = (r.get("credit_account") or "").strip()
        mapping_rows.append({
            "broker": broker,
            "type": typ,
            "subtype": sub,
            "description": desc,
            "debit_account": debit,
            "credit_account": credit,
            "updated_at": r.get("updated_at") or "",
            "updated_by": r.get("updated_by") or "",
            "source": r.get("source") or "",
            "rule_key": r.get("rule_key") or "",
        })

    # Preserve the original doc; inject normalized list under "mappings" for the template
    mapping = dict(raw_mapping) if isinstance(raw_mapping, dict) else {"raw": raw_mapping}
    mapping["mappings"] = mapping_rows  # <-- template expects mapping.mappings

    username, role = _current_user_and_role()
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
        mapping_rows=mapping_rows,
        user=username,
        user_role=role,
        from_source=from_source,
        entry_id=entry_id,
        coa_api_base=coa_api_base,
        api_urls=api_urls,
        has_seeded_rules=has_seeded_rules,  # optional banner in template
    )


# ---------------------------
# JSON APIs under /coa/api/* (expected by the UI)
# ---------------------------
@coa_mapping_web.route("/coa/api/mapping_table", methods=["GET"])
def mapping_table_api():
    """Return normalized mapping rows for client-side refresh."""
    try:
        mapping = load_mapping_table() or {}
        rules = _flatten_mapping_table(mapping)
        rows = []
        for r in rules:
            rows.append({
                "broker": r.get("broker"),
                "type": r.get("type"),
                "subtype": r.get("subtype"),
                "description": r.get("description"),
                # Show programmatic rule (single account) in the debit column for current UI
                "debit_account": (r.get("debit_account") or r.get("coa_account") or ""),
                "credit_account": (r.get("credit_account") or ""),
                "updated_at": r.get("updated_at") or "",
                "updated_by": r.get("updated_by") or "",
                "source": r.get("source") or "",
                "rule_key": r.get("rule_key") or "",
            })
        return jsonify({"ok": True, "rows": rows})
    except Exception as e:
        log_event("coa_mapping_web", f"mapping_table_api failed: {e}", level="error")
        return jsonify({"ok": False, "error": str(e)}), 500


@coa_mapping_web.route("/coa/api/get_mapping", methods=["POST"])
def api_get_mapping():
    try:
        txn = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        mapping = get_mapping_for_transaction(txn)
        return jsonify({"ok": True, "mapping": (mapping or {})})
    except Exception as e:
        log_event("coa_mapping_web", f"get_mapping failed: {e}", level="error")
        return jsonify({"ok": False, "error": str(e)}), 500


@coa_mapping_web.route("/coa/api/assign", methods=["POST"])
@admin_required
def api_assign():
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    try:
        mapping_rule = {
            "broker": data.get("broker"),
            "type": data.get("type"),
            "subtype": data.get("subtype"),
            "description": data.get("description"),
            "coa_account": data.get("coa_account"),
        }
        reason = data.get("reason", "manual assignment")
        actor, _ = _current_user_and_role()

        # Persist mapping
        assign_mapping(mapping_rule, user=actor, reason=reason)

        # Audit with enforced non-null event_type
        try:
            log_event_coa_mapping_updated(
                trade_id=None,
                status="resolved",
                compare_fields=mapping_rule,
                sync_run_id=None,
                api_hash=None,
                broker=mapping_rule.get("broker"),
                raw_record={"reason": reason, "actor": actor, "source": "coa_mapping_web.api_assign"},
                mapping_version=None,
                notes="COA mapping add/update",
                user_action="mapping_assign",
            )
        except Exception as _audit_err:
            # Do not block UI on audit failures; still log app-level event
            log_event("coa_mapping_web", f"audit write failed: {_audit_err}", level="error")

        # Decide response shape: JSON for AJAX, redirect for plain form POST
        is_ajax = (
            request.is_json
            or request.args.get("ajax") == "1"
            or request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest"
            or request.headers.get("Accept", "").startswith("application/json")
        )
        if is_ajax:
            return jsonify({"ok": True})
        flash("Mapping assigned/updated.", "success")
        try:
            return redirect(url_for("coa_mapping_web.view_mapping"))
        except Exception:
            return redirect("/coa_mapping")
    except ValueError as ve:
        if request.is_json:
            return jsonify({"ok": False, "error": str(ve)}), 400
        flash(str(ve), "danger")
        try:
            return redirect(url_for("coa_mapping_web.view_mapping"))
        except Exception:
            return redirect("/coa_mapping")
    except Exception as e:
        log_event("coa_mapping_web", f"assign failed: {e}", level="error")
        if request.is_json:
            return jsonify({"ok": False, "error": str(e)}), 500
        flash(f"Assign failed: {e}", "danger")
        try:
            return redirect(url_for("coa_mapping_web.view_mapping"))
        except Exception:
            return redirect("/coa_mapping")


@coa_mapping_web.route("/coa/api/versions", methods=["GET"])
def api_versions():
    try:
        mapping = load_mapping_table() or {}
        history = mapping.get("history", []) if isinstance(mapping, dict) else []
        return jsonify({"ok": True, "history": history})
    except Exception as e:
        log_event("coa_mapping_web", f"versions failed: {e}", level="error")
        return jsonify({"ok": False, "error": str(e)}), 500


@coa_mapping_web.route("/coa/api/rollback", methods=["POST"])
@admin_required
def api_rollback():
    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        version = int(payload.get("version") or 0)
    except Exception:
        return jsonify({"ok": False, "error": "invalid version"}), 400
    actor, _ = _current_user_and_role()
    if rollback_mapping_version(version):
        log_event("coa_mapping_web", f"Mapping table rolled back to version {version} by {actor}", level="info")
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "version not found"}), 404


@coa_mapping_web.route("/coa/api/export", methods=["GET"])
@admin_required
def api_export():
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


@coa_mapping_web.route("/coa/api/import", methods=["POST"])
@admin_required
def api_import():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "no file"}), 400
    file = request.files["file"]
    try:
        data = file.read().decode("utf-8")
        actor, _ = _current_user_and_role()
        import_mapping_table(data, user=actor)
        log_event("coa_mapping_web", f"Mapping table imported by {actor}.", level="info")
        return jsonify({"ok": True})
    except Exception as e:
        log_event("coa_mapping_web", f"import failed: {e}", level="error")
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------
# Back-compat routes under /coa_mapping/* (kept for callers that use them)
# ---------------------------
@coa_mapping_web.route("/coa_mapping/assign", methods=["POST"])
@admin_required
def assign_mapping_route():
    # delegate to API version
    return api_assign()


@coa_mapping_web.route("/coa_mapping/flag_unmapped", methods=["POST"])
def flag_unmapped():
    """Viewer can report; admin reviews later."""
    txn = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    actor, _ = _current_user_and_role()
    try:
        flag_unmapped_transaction(txn, user=actor)
        log_event("coa_mapping_web", f"Transaction flagged unmapped by {actor}: {txn}", level="info")
        return jsonify({"ok": True})
    except Exception as e:
        log_event("coa_mapping_web", f"flag_unmapped failed: {e}", level="error")
        return jsonify({"ok": False, "error": str(e)}), 500


@coa_mapping_web.route("/coa_mapping/versions", methods=["GET"])
def list_versions():
    return api_versions()


@coa_mapping_web.route("/coa_mapping/rollback", methods=["POST"])
@admin_required
def rollback_mapping():
    return api_rollback()


@coa_mapping_web.route("/coa_mapping/export", methods=["GET"])
@admin_required
def export_mapping():
    return api_export()


@coa_mapping_web.route("/coa_mapping/import", methods=["POST"])
@admin_required
def import_mapping():
    return api_import()


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

    Returns JSON only:
      - {"ok": true} on success
      - {"ok": false, "error": "..."} with 4xx/5xx on failures
    """
    data = request.get_json(silent=True) or request.form.to_dict()
    rule_key = (data.get("rule_key") or "").strip()
    account_code = (data.get("account_code") or data.get("coa_account") or "").strip()
    actor = (data.get("actor") or _current_user_and_role()[0]).strip()

    # Parse/merge context_meta (accept dict or JSON string). Build canonical dict if missing.
    cm_raw = data.get("context_meta")
    if isinstance(cm_raw, str) and cm_raw.strip():
        try:
            base_cm = json.loads(cm_raw)
            if not isinstance(base_cm, dict):
                base_cm = {"raw": cm_raw}
        except Exception:
            base_cm = {"raw": cm_raw}
    elif isinstance(cm_raw, dict):
        base_cm = dict(cm_raw)
    else:
        base_cm = {}

    # Derive canonical fields from top-level inputs; do not overwrite explicit context_meta keys.
    def _first(*keys):
        for k in keys:
            v = data.get(k)
            if v is not None and str(v).strip() != "":
                return v
        return None

    derived = {
        "broker_code": _first("broker_code", "broker"),
        "type": _first("trn_type", "type", "txn_type", "action", "subtype", "import_type"),
        "symbol": _first("symbol"),
        "memo": _first("memo", "description", "desc", "notes"),
        "strategy": _first("strategy"),
        "trade_id": _first("trade_id"),
        "group_id": _first("group_id"),
        "source": _first("source") or "coa_mapping_web",
    }
    # Merge without clobbering existing explicit keys
    for k, v in derived.items():
        if k not in base_cm and v is not None:
            base_cm[k] = v

    if not account_code:
        return jsonify({"ok": False, "error": "missing account_code"}), 400

    try:
        # Call the canonical writer with supported parameters
        upsert_rule(rule_key=rule_key, account_code=account_code, context_meta=base_cm, actor=actor)
        log_event("coa_mapping_web",
                  f"internal upsert_rule by {actor}: rule_key={rule_key or '(derived)'}, account_code={account_code}",
                  level="info")
        return jsonify({"ok": True})
    except ValueError as ve:
        # Input/validation problems → 400
        log_event("coa_mapping_web", f"internal upsert_rule validation error: {ve}", level="warning")
        return jsonify({"ok": False, "error": str(ve)}), 400
    except Exception as e:
        # Unexpected issues → 500
        log_event("coa_mapping_web", f"internal upsert_rule failed: {e}", level="error")
        return jsonify({"ok": False, "error": str(e)}), 500
