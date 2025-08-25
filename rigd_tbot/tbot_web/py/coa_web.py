# tbot_web/py/coa_web.py
# Dedicated page and API endpoints for human-readable COA viewing/editing via Web UI

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    session,
    send_file,
    flash,
)

from tbot_web.support.auth_web import rbac_required
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import (
    validate_bot_identity,
    get_bot_identity_string_regex,
)

# ---- Preferred provider: ledger_modules service (no direct file writes here)
# Fallback to utils_coa_web ONLY if the service is absent.
try:
    from tbot_bot.accounting.ledger_modules import coa_service as _coa  # type: ignore
    _PROVIDER = "ledger_modules"
except Exception:  # pragma: no cover
    from tbot_web.support import utils_coa_web as _coa  # type: ignore
    _PROVIDER = "utils"

coa_web = Blueprint("coa_web", __name__, template_folder="../templates")


# -----------------
# Helpers
# -----------------

def utcnow() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc)


def identity_guard() -> bool:
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


def _safe_json(val: Any) -> str:
    try:
        return json.dumps(val, ensure_ascii=False, indent=2)
    except Exception:
        return "[]"


# -----------------
# Page
# -----------------

@coa_web.route("/coa", methods=["GET"])
@rbac_required()  # viewer/trader/admin can view
def coa_management():
    if identity_guard():
        return render_template(
            "coa.html",
            user_is_admin=(session.get("role", "") == "admin"),
            coa_json=None,
            error="Bot identity not available, please complete configuration.",
        )
    try:
        # Provider should return a dict with at least: {metadata, accounts, versions?}
        data = _coa.load_coa_metadata_and_accounts()  # uniform name in both providers
        coa_json = _safe_json(data.get("accounts", []))
        return render_template(
            "coa.html",
            user_is_admin=(session.get("role", "") == "admin"),
            coa_json=coa_json,
            error=None,
        )
    except FileNotFoundError:
        return render_template(
            "coa.html",
            user_is_admin=(session.get("role", "") == "admin"),
            coa_json=None,
            error="COA or metadata file not found. Please initialize via admin tools.",
        )
    except Exception as e:
        return render_template(
            "coa.html",
            user_is_admin=(session.get("role", "") == "admin"),
            coa_json=None,
            error=f"COA error: {e}",
        )


# -----------------
# API: get current COA (+ history)
# -----------------

@coa_web.route("/coa/api", methods=["GET"])
@rbac_required()
def coa_api():
    if identity_guard():
        return jsonify({"error": "Bot identity not available, please complete configuration."}), 400
    try:
        data = _coa.load_coa_metadata_and_accounts()
        metadata = data.get("metadata", {})
        accounts = data.get("accounts", [])
        # Optional hooks (ledger_modules preferred)
        history = []
        try:
            history = _coa.get_coa_audit_log(limit=50)  # both providers expose this
        except Exception:
            history = []
        # Versions (best-effort if provider implements)
        versions = []
        try:
            versions = _coa.list_versions()  # ledger_modules service
        except Exception:
            # utils provider may lack versions; ignore silently
            versions = []
        return jsonify({"metadata": metadata, "accounts": accounts, "history": history, "versions": versions, "provider": _PROVIDER})
    except FileNotFoundError:
        return jsonify({"error": "COA or metadata file not found. Please initialize via admin tools."}), 400
    except Exception as e:
        return jsonify({"error": f"COA error: {e}"}), 400


# -----------------
# API: versions
# -----------------

@coa_web.route("/coa/versions", methods=["GET"])
@rbac_required()
def coa_list_versions():
    if identity_guard():
        return jsonify({"error": "Bot identity not available, please complete configuration."}), 400
    try:
        versions = _coa.list_versions()  # ledger_modules service
        return jsonify({"versions": versions})
    except AttributeError:
        # Fallback if provider doesn't support versions
        return jsonify({"versions": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@coa_web.route("/coa/version/<int:version_id>", methods=["GET"])
@rbac_required()
def coa_get_version(version_id: int):
    if identity_guard():
        return jsonify({"error": "Bot identity not available, please complete configuration."}), 400
    try:
        data = _coa.load_version(version_id)  # ledger_modules service
        return jsonify({"version_id": version_id, "accounts": data.get("accounts", []), "metadata": data.get("metadata", {})})
    except AttributeError:
        return jsonify({"error": "Versioning is not supported by this provider."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# -----------------
# API: structure CRUD (admin)
# -----------------

@coa_web.route("/coa/edit", methods=["POST"])
@rbac_required(role="admin")
def coa_edit():
    """
    Replace the entire COA accounts tree (append-only versioned in provider).
    Body (form or JSON): { "coa_json": "<json array>" } OR direct JSON array.
    """
    if identity_guard():
        return "Bot identity not available, please complete configuration.", 400

    raw = request.form.get("coa_json")
    if raw is None:
        # Accept raw JSON body too
        raw = request.get_data(as_text=True) or "[]"

    try:
        new_accounts = json.loads(raw)
        # Validate via provider
        if hasattr(_coa, "validate_coa_json"):
            _coa.validate_coa_json(new_accounts)
        # Compute diff if provider exposes it (for audit)
        diff = None
        try:
            current = _coa.load_coa_metadata_and_accounts().get("accounts", [])
            if hasattr(_coa, "compute_coa_diff"):
                diff = _coa.compute_coa_diff(current, new_accounts)
        except Exception:
            diff = None

        user = session.get("user", "unknown")
        reason = request.form.get("reason") or "web-edit"
        # Save via provider (versioned/atomic)
        if hasattr(_coa, "save_coa_json"):
            _coa.save_coa_json(new_accounts, user=user, diff=diff, reason=reason)
        elif hasattr(_coa, "save_coa_tree"):
            _coa.save_coa_tree(new_accounts, user=user, reason=reason, diff=diff)
        else:
            raise RuntimeError("COA provider does not support saving.")

        return redirect(url_for("coa_web.coa_management"))
    except Exception as e:
        return f"Error updating COA: {str(e)}", 400


@coa_web.route("/coa/api/node", methods=["POST"])
@rbac_required(role="admin")
def coa_node_crud():
    """
    Node-level CRUD for the accounts tree.

    JSON body:
      {
        "action": "add" | "update" | "delete",
        "node": { ... account object ... },
        "parent_code": "xxx"      # required for add under parent (if provider needs it)
      }
    """
    if identity_guard():
        return jsonify({"ok": False, "error": "identity"}), 400

    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").lower()
    node = payload.get("node") or {}
    parent_code = payload.get("parent_code")

    try:
        # Prefer granular provider methods; fall back to edit-in-memory then save.
        if hasattr(_coa, "node_crud"):
            res = _coa.node_crud(action=action, node=node, parent_code=parent_code, user=session.get("user", "unknown"))
            return jsonify({"ok": True, "result": res})

        # Fallback path: modify tree locally then save via provider’s save()
        data = _coa.load_coa_metadata_and_accounts()
        accounts = data.get("accounts", [])

        def _index_by_code(acc_list):
            idx = {}
            for a in acc_list:
                c = a.get("code")
                if c:
                    idx[c] = a
                for ch in a.get("children", []) or []:
                    for k, v in _index_by_code([ch]).items():
                        idx[k] = v
            return idx

        idx = _index_by_code(accounts)

        if action == "add":
            if not parent_code:
                accounts.append(node)
            else:
                parent = idx.get(parent_code)
                if not parent:
                    return jsonify({"ok": False, "error": "parent_not_found"}), 400
                parent.setdefault("children", []).append(node)

        elif action == "update":
            code = node.get("code")
            if not code or code not in idx:
                return jsonify({"ok": False, "error": "node_not_found"}), 400
            target = idx[code]
            # shallow update only for safety
            for k, v in node.items():
                if k != "children":
                    target[k] = v

        elif action == "delete":
            code = node.get("code")
            if not code:
                return jsonify({"ok": False, "error": "missing_code"}), 400

            def _delete_inplace(lst: List[Dict]) -> bool:
                for i, a in enumerate(list(lst)):
                    if a.get("code") == code:
                        lst.pop(i)
                        return True
                    if _delete_inplace(a.get("children", []) or []):
                        return True
                return False

            if not _delete_inplace(accounts):
                return jsonify({"ok": False, "error": "node_not_found"}), 404

        else:
            return jsonify({"ok": False, "error": "invalid_action"}), 400

        # Validate and save
        if hasattr(_coa, "validate_coa_json"):
            _coa.validate_coa_json(accounts)
        user = session.get("user", "unknown")
        reason = f"node_{action}"
        if hasattr(_coa, "save_coa_json"):
            _coa.save_coa_json(accounts, user=user, diff=None, reason=reason)
        elif hasattr(_coa, "save_coa_tree"):
            _coa.save_coa_tree(accounts, user=user, diff=None, reason=reason)
        else:
            raise RuntimeError("COA provider does not support saving.")

        return jsonify({"ok": True})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# -----------------
# Export
# -----------------

@coa_web.route("/coa/export/markdown", methods=["GET"])
@rbac_required()
def coa_export_markdown():
    if identity_guard():
        return "Bot identity not available, please complete configuration.", 400
    try:
        data = _coa.load_coa_metadata_and_accounts()
        # Prefer provider’s export to avoid controller-level file logic
        if hasattr(_coa, "export_coa_markdown"):
            md = _coa.export_coa_markdown(data)
        else:
            # utils provider compatibility
            md = _coa.export_coa_markdown(data)
        buf = io.BytesIO(md.encode("utf-8"))
        ts = utcnow().strftime("%Y%m%dT%H%M%SZ")
        filename = f"COA_{data.get('metadata', {}).get('entity_code','')}_{ts}.md"
        return send_file(buf, mimetype="text/markdown", as_attachment=True, download_name=filename)
    except FileNotFoundError:
        return "COA or metadata file not found. Please initialize via admin tools.", 400
    except Exception as e:
        return f"COA error: {e}", 400


@coa_web.route("/coa/export/csv", methods=["GET"])
@rbac_required()
def coa_export_csv():
    if identity_guard():
        return "Bot identity not available, please complete configuration.", 400
    try:
        data = _coa.load_coa_metadata_and_accounts()
        if hasattr(_coa, "export_coa_csv"):
            csv_txt = _coa.export_coa_csv(data)
        else:
            csv_txt = _coa.export_coa_csv(data)
        buf = io.BytesIO(csv_txt.encode("utf-8"))
        ts = utcnow().strftime("%Y%m%dT%H%M%SZ")
        filename = f"COA_{data.get('metadata', {}).get('entity_code','')}_{ts}.csv"
        return send_file(buf, mimetype="text/csv", as_attachment=True, download_name=filename)
    except FileNotFoundError:
        return "COA or metadata file not found. Please initialize via admin tools.", 400
    except Exception as e:
        return f"COA error: {e}", 400


# -----------------
# RBAC probe (unchanged)
# -----------------

@coa_web.route("/coa/rbac", methods=["GET"])
def coa_rbac_status():
    user_is_admin = session.get("role", "") == "admin"
    return jsonify({"user_is_admin": user_is_admin})
