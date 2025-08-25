# tbot_web/py/ledger_web.py

import traceback
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import (
    validate_bot_identity,
    get_bot_identity_string_regex,
)
from tbot_web.support.auth_web import get_current_user, get_user_role
from tbot_bot.config.env_bot import get_bot_config
from tbot_web.support.utils_coa_web import load_coa_metadata_and_accounts

# Read-only/grouping/balances/search via ledger_modules
from tbot_bot.accounting.ledger_modules.ledger_grouping import (
    fetch_grouped_trades,
    fetch_trade_group_by_id,
    collapse_expand_group,
)
from tbot_bot.accounting.ledger_modules.ledger_query import search_trades, query_balances

# Mutations via ledger façade/modules (no direct SQL)
from tbot_bot.accounting.ledger import (
    post_ledger_entries_double_entry,
    edit_ledger_entry,
    delete_ledger_entry,
    mark_entry_resolved,
    sync_broker_ledger,
)

ledger_web = Blueprint("ledger_web", __name__)

BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
INITIALIZE_STATES = ("initialize", "provisioning", "bootstrapping")


# -----------------
# Guards & RBAC
# -----------------

def get_current_bot_state():
    try:
        with open(BOT_STATE_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def provisioning_guard():
    state = get_current_bot_state()
    if state in INITIALIZE_STATES:
        flash("Provisioning not complete. Ledger access is unavailable.")
        return True
    return False


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


def _role_allowed(action: str) -> bool:
    """
    Very small RBAC: viewer < trader < admin
    - view: viewer/trader/admin
    - group toggle: viewer/trader/admin
    - add/edit/sync: trader/admin
    - delete: admin
    """
    role = (get_user_role() or "viewer").lower()
    if action in ("view", "group_toggle"):
        return role in ("viewer", "trader", "admin")
    if action in ("add", "edit", "sync"):
        return role in ("trader", "admin")
    if action == "delete":
        return role in ("admin",)
    return False


def _is_display_entry(entry):
    # True if at least one primary display field is present/non-empty
    return bool(
        (entry.get("symbol") and str(entry.get("symbol")).strip())
        or (entry.get("datetime_utc") and str(entry.get("datetime_utc")).strip())
        or (entry.get("action") and str(entry.get("action")).strip())
        or (entry.get("price") not in (None, "", "None"))
        or (entry.get("quantity") not in (None, "", "None"))
        or (entry.get("total_value") not in (None, "", "None"))
    )


# -----------------
# Routes
# -----------------

@ledger_web.route('/ledger/reconcile', methods=['GET', 'POST'])
def ledger_reconcile():
    if provisioning_guard() or identity_guard():
        return render_template(
            'ledger.html',
            entries=[],
            error="Ledger access not available (provisioning or identity incomplete).",
            balances={},
            coa_accounts=[],
        )
    if not _role_allowed("view"):
        return render_template(
            'ledger.html',
            entries=[],
            error="You do not have permission to view the ledger.",
            balances={},
            coa_accounts=[],
        )

    error = None
    try:
        # Balances via ledger_modules (no raw SQL)
        balances_rows = query_balances()
        balances = {row["account"]: {
            "opening_balance": str(row["opening_balance"]),
            "debits": str(row["debits"]),
            "credits": str(row["credits"]),
            "closing_balance": str(row["closing_balance"]),
        } for row in balances_rows}

        coa_data = load_coa_metadata_and_accounts()
        coa_accounts = coa_data.get("accounts_flat", [])  # list of (code, name)

        # Use grouped view by default (collapsed)
        entries = fetch_grouped_trades()
        entries = [e for e in entries if _is_display_entry(e)]

        return render_template('ledger.html', entries=entries, error=error, balances=balances, coa_accounts=coa_accounts)

    except Exception as e:
        error = f"Ledger error: {e}"
        traceback.print_exc()
        return render_template('ledger.html', entries=[], error=error, balances={}, coa_accounts=[])


@ledger_web.route('/ledger/group/<group_id>', methods=['GET'])
def ledger_group_detail(group_id):
    if provisioning_guard() or identity_guard():
        return jsonify({"error": "Not permitted"}), 403
    if not _role_allowed("view"):
        return jsonify({"error": "Forbidden"}), 403
    try:
        group = fetch_trade_group_by_id(group_id)
        return jsonify(group)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@ledger_web.route('/ledger/collapse_expand/<group_id>', methods=['POST'])
def ledger_collapse_expand(group_id):
    if provisioning_guard() or identity_guard():
        return jsonify({"ok": False, "error": "Not permitted"}), 403
    if not _role_allowed("group_toggle"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    try:
        # Accept optional explicit state from the client.
        # convention: collapsed_state = 1 means "collapsed", 0 means "expanded"
        data = request.get_json(silent=True) or {}
        collapsed_state = data.get("collapsed_state", None)
        if collapsed_state is not None:
            # normalize to 0/1
            collapsed_state = 1 if str(collapsed_state).lower() in ("1", "true", "yes") else 0
            result = collapse_expand_group(group_id, collapsed_state=collapsed_state)
        else:
            # no state provided -> toggle
            result = collapse_expand_group(group_id)

        return jsonify({"ok": True, "result": bool(result), "collapsed_state": collapsed_state})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ledger_web.route('/ledger/collapse_all', methods=['POST'])
def ledger_collapse_all():
    """
    Collapse or expand ALL groups in one shot.
    Accepts JSON in any of these shapes:
      {"collapse": true}          -> collapse all
      {"collapse": false}         -> expand all
      {"collapsed_state": 1|0}    -> 1 collapse, 0 expand
      {"expanded": true|false}    -> inverse of collapsed_state
    """
    if provisioning_guard() or identity_guard():
        return jsonify({"ok": False, "error": "Not permitted"}), 403
    if not _role_allowed("group_toggle"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    try:
        data = request.get_json(silent=True) or {}
        if "collapse" in data:
            collapsed_state = 1 if bool(data["collapse"]) else 0
        elif "collapsed_state" in data:
            collapsed_state = 1 if str(data["collapsed_state"]).lower() in ("1", "true", "yes") else 0
        elif "expanded" in data:
            collapsed_state = 0 if bool(data["expanded"]) else 1
        else:
            return jsonify({"ok": False, "error": "missing collapse/expanded flag"}), 400

        # Fetch current groups (collapsed view is fine; we only need IDs)
        groups = fetch_grouped_trades(collapse=True, limit=10000)
        group_ids = [g.get("group_id") or g.get("trade_id") for g in groups if g]
        group_ids = [gid for gid in group_ids if gid]

        changed = 0
        for gid in group_ids:
            try:
                collapse_expand_group(gid, collapsed_state=collapsed_state)
                changed += 1
            except Exception:
                traceback.print_exc()

        return jsonify({"ok": True, "collapsed_state": collapsed_state, "count": changed})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@ledger_web.route('/ledger/search', methods=['GET'])
def ledger_search():
    if provisioning_guard() or identity_guard():
        return jsonify({"error": "Not permitted"}), 403
    if not _role_allowed("view"):
        return jsonify({"error": "Forbidden"}), 403
    query = request.args.get('q', '').strip()
    sort_by = request.args.get('sort_by', 'datetime_utc')
    sort_desc = request.args.get('sort_desc', '1') == '1'
    try:
        results = search_trades(search_term=query, sort_by=sort_by, sort_desc=sort_desc)
        results = [e for e in results if _is_display_entry(e)]
        return jsonify(results)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@ledger_web.route('/ledger/resolve/<int:entry_id>', methods=['POST'])
def resolve_ledger_entry(entry_id):
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    if not _role_allowed("edit"):
        flash('Not permitted.', 'error')
        return redirect(url_for('ledger_web.ledger_reconcile'))
    mark_entry_resolved(entry_id)
    flash('Entry marked as resolved.')
    return redirect(url_for('ledger_web.ledger_reconcile'))


@ledger_web.route('/ledger/add', methods=['POST'])
def add_ledger_entry_route():
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    if not _role_allowed("add"):
        flash('Not permitted.', 'error')
        return redirect(url_for('ledger_web.ledger_reconcile'))

    form = request.form
    bot_identity = load_bot_identity()
    entity_code, jurisdiction_code, broker, bot_id = bot_identity.split("_")
    current_user = get_current_user()
    config = get_bot_config()

    def _num(val, default=None):
        try:
            return float(val)
        except Exception:
            return default

    entry_data = {
        "datetime_utc": form.get("datetime_utc"),
        "symbol": form.get("symbol"),
        "action": form.get("action"),
        "quantity": _num(form.get("quantity")),
        "price": _num(form.get("price")),
        "total_value": _num(form.get("total_value")),
        "fee": _num(form.get("fee"), 0.0),
        "account": form.get("account"),
        "strategy": form.get("strategy"),
        "trade_id": form.get("trade_id"),
        "tags": form.get("tags"),
        "notes": form.get("notes"),
        "jurisdiction_code": jurisdiction_code,
        "entity_code": entity_code,
        "language": config.get("LANGUAGE_CODE", "en"),
        "created_by": getattr(current_user, "username", None) or (current_user if current_user else "system"),
        "updated_by": getattr(current_user, "username", None) or (current_user if current_user else "system"),
        "approved_by": getattr(current_user, "username", None) or (current_user if current_user else "system"),
        "approval_status": "pending",
        "gdpr_compliant": True,
        "ccpa_compliant": True,
        "pipeda_compliant": True,
        "hipaa_sensitive": False,
        "iso27001_tag": "",
        "soc2_type": "",
    }
    try:
        # amount sign/side handled inside double-entry mapping,
        # but provide a sane numeric default for pre-validation.
        entry_data["amount"] = _num(entry_data.get("total_value"), 0.0) or 0.0
        post_ledger_entries_double_entry([entry_data])
        flash('Ledger entry added (double-entry compliant).')
    except Exception as e:
        traceback.print_exc()
        flash(f"Ledger error: {e}", "error")
    return redirect(url_for('ledger_web.ledger_reconcile'))


@ledger_web.route('/ledger/edit/<int:entry_id>', methods=['POST'])
def edit_ledger_entry_route(entry_id):
    """
    Full edit (legacy) — keeps behavior for forms that post many fields.
    If you only want to change the COA account, use /ledger/update_account/<id>.
    """
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    if not _role_allowed("edit"):
        flash('Not permitted.', 'error')
        return redirect(url_for('ledger_web.ledger_reconcile'))

    form = request.form
    bot_identity = load_bot_identity()
    entity_code, jurisdiction_code, broker, bot_id = bot_identity.split("_")
    current_user = get_current_user()
    config = get_bot_config()

    def _num(val, default=None):
        try:
            return float(val)
        except Exception:
            return default

    updated_data = {
        "datetime_utc": form.get("datetime_utc"),
        "symbol": form.get("symbol"),
        "action": form.get("action"),
        "quantity": _num(form.get("quantity")),
        "price": _num(form.get("price")),
        "total_value": _num(form.get("total_value")),
        "fee": _num(form.get("fee"), 0.0),
        "account": form.get("account"),
        "strategy": form.get("strategy"),
        "trade_id": form.get("trade_id"),
        "tags": form.get("tags"),
        "notes": form.get("notes"),
        "jurisdiction_code": jurisdiction_code,
        "entity_code": entity_code,
        "language": config.get("LANGUAGE_CODE", "en"),
        "updated_by": getattr(current_user, "username", None) or (current_user if current_user else "system"),
        "approval_status": form.get("approval_status", "pending"),
        "gdpr_compliant": True,
        "ccpa_compliant": True,
        "pipeda_compliant": True,
        "hipaa_sensitive": False,
        "iso27001_tag": "",
        "soc2_type": "",
    }
    try:
        updated_data["amount"] = _num(updated_data.get("total_value"), 0.0) or 0.0
        edit_ledger_entry(entry_id, updated_data)
        flash('Ledger entry updated.')
    except Exception as e:
        traceback.print_exc()
        flash(f"Ledger error: {e}", "error")
    return redirect(url_for('ledger_web.ledger_reconcile'))


# ---------- Updated: COA account updater (no raw SQL; supports whole-group with provided group_id) ----------

def _valid_account_code(code: str) -> bool:
    if not code:
        return False
    try:
        coa = load_coa_metadata_and_accounts()
        valid_codes = {c for c, _n in (coa.get("accounts_flat", []) or [])}
        return code in valid_codes
    except Exception:
        return False


@ledger_web.route('/ledger/update_account/<int:entry_id>', methods=['POST'])
def update_ledger_account_route(entry_id: int):
    """
    Update only the COA account (and optionally strategy) for a single ledger row.
    Optional form fields:
      - account (required)
      - strategy (optional)
      - apply_to_group: "1" to apply to all rows with the same group_id (requires 'group_id' param)
      - group_id (optional, required if apply_to_group=1)
    """
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    if not _role_allowed("edit"):
        flash('Not permitted.', 'error')
        return redirect(url_for('ledger_web.ledger_reconcile'))

    account = (request.form.get("account") or "").strip()
    strategy = (request.form.get("strategy") or "").strip() or None
    apply_to_group = str(request.form.get("apply_to_group", "0")).lower() in ("1", "true", "yes")
    group_id = (request.form.get("group_id") or "").strip()

    if not _valid_account_code(account):
        flash("Invalid account code.", "error")
        return redirect(url_for('ledger_web.ledger_reconcile'))

    try:
        if apply_to_group:
            if not group_id:
                flash("group_id is required to apply changes to the whole group.", "error")
                return redirect(url_for('ledger_web.ledger_reconcile'))
            # Fetch entries in group and patch each via edit_ledger_entry
            group = fetch_trade_group_by_id(group_id)
            changed = 0
            for row in group or []:
                payload = {"account": account}
                if strategy is not None:
                    payload["strategy"] = strategy
                edit_ledger_entry(int(row["id"]), payload)
                changed += 1
            flash(f"Account updated for {changed} entries in group {group_id}.")
        else:
            payload = {"account": account}
            if strategy is not None:
                payload["strategy"] = strategy
            edit_ledger_entry(entry_id, payload)
            flash("Account updated.")
    except Exception as e:
        traceback.print_exc()
        flash(f"Failed to update account: {e}", "error")

    return redirect(url_for('ledger_web.ledger_reconcile'))


@ledger_web.route('/ledger/update_account_json', methods=['POST'])
def update_ledger_account_json():
    """
    JSON variant for XHR updates.
    Body: {"entry_id": 123, "account": "Assets:Cash", "strategy":"open", "apply_to_group": true, "group_id": "..." }
    """
    if provisioning_guard() or identity_guard():
        return jsonify({"ok": False, "error": "Not permitted"}), 403
    if not _role_allowed("edit"):
        return jsonify({"ok": False, "error": "Forbidden"}), 403

    data = request.get_json(silent=True) or {}
    try:
        entry_id = int(data.get("entry_id"))
    except Exception:
        return jsonify({"ok": False, "error": "missing/invalid entry_id"}), 400

    account = (data.get("account") or "").strip()
    strategy = (data.get("strategy") or "").strip() or None
    apply_to_group = bool(data.get("apply_to_group", False))
    group_id = (data.get("group_id") or "").strip()

    if not _valid_account_code(account):
        return jsonify({"ok": False, "error": "invalid account code"}), 400

    try:
        if apply_to_group:
            if not group_id:
                return jsonify({"ok": False, "error": "group_id required for group update"}), 400
            group = fetch_trade_group_by_id(group_id)
            changed = 0
            for row in group or []:
                payload = {"account": account}
                if strategy is not None:
                    payload["strategy"] = strategy
                edit_ledger_entry(int(row["id"]), payload)
                changed += 1
            return jsonify({"ok": True, "updated": changed, "group_id": group_id})
        else:
            payload = {"account": account}
            if strategy is not None:
                payload["strategy"] = strategy
            edit_ledger_entry(entry_id, payload)
            return jsonify({"ok": True, "updated": 1})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@ledger_web.route('/ledger/delete/<int:entry_id>', methods=['POST'])
def delete_ledger_entry_route(entry_id):
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    if not _role_allowed("delete"):
        flash('Not permitted.', 'error')
        return redirect(url_for('ledger_web.ledger_reconcile'))
    delete_ledger_entry(entry_id)
    flash('Ledger entry deleted.')
    return redirect(url_for('ledger_web.ledger_reconcile'))


@ledger_web.route('/ledger/sync', methods=['POST'])
def ledger_sync():
    """
    Kicks off broker->ledger sync using the orchestrator.
    Uses orchestrator summary (no raw SQL).
    """
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    if not _role_allowed("sync"):
        flash('Not permitted.', 'error')
        return redirect(url_for('ledger_web.ledger_reconcile'))

    try:
        print("[WEB] /ledger/sync: invoked")
        summary = sync_broker_ledger()
        status = summary.get("status", "unknown")
        rows = summary.get("inserted_rows", 0)
        groups = summary.get("posted_groups", 0)
        skipped = summary.get("dedup_skipped", 0)
        rejected = summary.get("rejected", 0)

        if rejected:
            flash(f"Sync finished with rejects. inserted={rows}, groups={groups}, dedup_skipped={skipped}, rejected={rejected}", "error")
        else:
            flash(f"Broker ledger synced. inserted={rows}, groups={groups}, dedup_skipped={skipped}")

        print(f"[WEB] /ledger/sync: completed - {summary}")
    except Exception as e:
        traceback.print_exc()
        print("[WEB] /ledger/sync: ERROR:", repr(e))
        flash(f"Broker ledger sync failed: {e}", "error")
    return redirect(url_for('ledger_web.ledger_reconcile'))
