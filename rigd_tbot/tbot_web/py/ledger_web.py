# tbot_web/py/ledger_web.py

import csv
import io
import traceback
import sqlite3
from pathlib import Path
from typing import Tuple, Dict, Any, List
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    current_app,
)
from werkzeug.routing import BuildError

from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import (
    validate_bot_identity,
    get_bot_identity_string_regex,
    resolve_ledger_db_path,
)
from tbot_web.support.auth_web import get_current_user, get_user_role  # DB-backed RBAC
from tbot_bot.config.env_bot import get_bot_config
from tbot_web.support.utils_coa_web import load_coa_metadata_and_accounts

from tbot_bot.accounting.ledger_modules.ledger_grouping import (
    fetch_grouped_trades,
    fetch_trade_group_by_id,
    collapse_expand_group,
)
from tbot_bot.accounting.ledger_modules.ledger_query import search_trades

# Balance/running-balance helpers
from tbot_bot.accounting.ledger_modules.ledger_balance import calculate_account_balances

ledger_web = Blueprint("ledger_web", __name__)

BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
INITIALIZE_STATES = ("initialize", "provisioning", "bootstrapping")


# ---------------------------
# Guards / RBAC
# ---------------------------
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


def _current_user_and_role() -> Tuple[Any, str]:
    """
    Return (user_object_or_username, role) with role fetched live from SYSTEM_USERS (viewer on failure).
    """
    user = get_current_user()
    username = getattr(user, "username", None) or user or session.get("user")
    role = get_user_role(username) if username else "viewer"
    return (user or username), role


def _require_admin_post():
    """
    Enforce: viewer → GET only; admin → POST allowed.
    """
    _, role = _current_user_and_role()
    if request.method == "POST" and role != "admin":
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return None


# ---------------------------
# COA helpers (ensures dropdown is always populated)
# ---------------------------
def _get_coa_lists():
    """
    Returns (accounts_flat, accounts_flat_dropdown, metadata)
    """
    data = load_coa_metadata_and_accounts()
    flat = data.get("accounts_flat", []) or []
    flat_dd = data.get("accounts_flat_dropdown", []) or flat  # fallback to flat if dropdown missing
    meta = data.get("metadata", {}) or {}
    return flat, flat_dd, meta


# ---------------------------
# Utilities
# ---------------------------
def _is_display_entry(entry: Dict[str, Any]) -> bool:
    return bool(
        (entry.get("symbol") and str(entry.get("symbol")).strip())
        or (entry.get("datetime_utc") and str(entry.get("datetime_utc")).strip())
        or (entry.get("action") and str(entry.get("action")).strip())
        or (entry.get("price") not in (None, "", "None"))
        or (entry.get("quantity") not in (None, "", "None"))
        or (entry.get("total_value") not in (None, "", "None"))
    )


def _valid_account_code(code: str) -> bool:
    if not code:
        return False
    try:
        flat, _flat_dd, _meta = _get_coa_lists()
        valid_codes = {c for c, _n in (flat or [])}
        return code in valid_codes
    except Exception:
        return False


def _has_unmapped(entries: List[Dict[str, Any]]) -> bool:
    for e in entries or []:
        if e.get("unmapped"):
            return True
        for s in (e.get("sub_entries") or []):
            if s.get("unmapped") or not s.get("account"):
                return True
    return False


def _sort_key_mapping(field: str) -> str:
    """
    Map canonical sort keys (top/bottom header rows) to DB/aggregate fields.
    """
    field = (field or "").strip().lower()
    mapping = {
        # top header
        "datetime_utc": "datetime_utc",
        "symbol": "symbol",
        "account": "account",            # consolidated account model
        "action": "action",
        "quantity": "quantity",
        "price": "price",
        "fee": "fee",
        "total_value": "total_value",
        "status": "status",
        "running_balance": "running_balance",
        # bottom header
        "trade_id": "trade_id",
        "strategy": "strategy",
        "tags": "tags",
        "notes": "notes",
        "action_detail": "action",       # closest proxy
    }
    return mapping.get(field, "datetime_utc")


def _get_sort_params() -> Tuple[str, bool]:
    col = request.args.get("sort", request.args.get("sort_by", "datetime_utc"))
    col = _sort_key_mapping(col)
    dir_val = request.args.get("dir", None)
    if dir_val is None:
        dir_val = "desc" if request.args.get("sort_desc", "1") == "1" else "asc"
    desc = str(dir_val).lower() not in ("asc", "ascending")
    return col, desc


def _python_sort_groups(entries: List[Dict[str, Any]], sort_col: str, sort_desc: bool) -> List[Dict[str, Any]]:
    """
    Stable fallback sort in Python when fetch_grouped_trades() doesn't support sort kwargs yet.
    """
    col_map = {
        "trade_id": "datetime_utc",
        "strategy": "action",
        "tags": "action",
        "notes": "action",
        "action_detail": "action",
    }
    key = col_map.get(sort_col, sort_col or "datetime_utc")

    def safe(v):
        return "" if v is None else v

    try:
        entries.sort(key=lambda e: (safe(e.get(key)), safe(e.get("datetime_utc"))), reverse=bool(sort_desc))
    except Exception:
        entries.sort(key=lambda e: safe(e.get("datetime_utc")), reverse=bool(sort_desc))
    return entries


# --- Audit-trail migration helpers (surgical, non-blocking) ---
def _table_exists(conn, table: str) -> bool:
    try:
        return bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                (table,),
            ).fetchone()
        )
    except Exception:
        return False


def _ensure_audit_trail_columns():
    """
    Backwards-compatible migration: add columns audit logger expects if they're missing.
    Safe on SQLite: ADD COLUMN with NULL default is instant and non-destructive.
    Never blocks the UI; logs tracebacks only.
    """
    try:
        bot_identity = load_bot_identity() or ""
        e, j, b, bot_id = bot_identity.split("_", 3)
        db_path = resolve_ledger_db_path(e, j, b, bot_id)
        if not db_path:
            return
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "audit_trail"):
                return
            # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
            have = {row[1] for row in conn.execute("PRAGMA table_info(audit_trail)").fetchall()}
            needed = ["entity_code", "jurisdiction_code", "broker_code", "bot_id", "actor", "reason"]
            for col in needed:
                if col not in have:
                    conn.execute(f"ALTER TABLE audit_trail ADD COLUMN {col} TEXT")
    except Exception:
        # never block UI because of migration; the write will still fail if something else is wrong
        traceback.print_exc()


# ---------------------------
# Routes  (dual aliases to avoid /ledger/ledger/* issues)
# ---------------------------

@ledger_web.route("/", methods=["GET"])
def ledger_root():
    return redirect(url_for("ledger_web.ledger_reconcile"))


@ledger_web.route("/reconcile", methods=["GET"])
def ledger_reconcile():
    # RBAC: viewers allowed (GET)
    error = None
    entries: List[Dict[str, Any]] = []
    balances: Dict[str, Any] = {}
    coa_accounts: List[Tuple[str, str]] = []
    coa_accounts_dropdown: List[Tuple[str, str]] = []
    coa_meta: Dict[str, Any] = {}

    if provisioning_guard() or identity_guard():
        return render_template(
            "ledger.html",
            entries=entries,
            error="Ledger access not available (provisioning or identity incomplete).",
            balances=balances,
            coa_accounts=coa_accounts,
            coa_accounts_dropdown=coa_accounts_dropdown,
            coa_meta=coa_meta,
            user_role="viewer",
            has_unmapped=False,
        )
    try:
        # Include opening equity/initial funding in balances (fallback if older signature)
        try:
            balances = calculate_account_balances(include_opening=True)
        except TypeError:
            balances = calculate_account_balances()
        except Exception:
            balances = {}

        # COA lists (both shapes for UI)
        coa_accounts, coa_accounts_dropdown, coa_meta = _get_coa_lists()

        # grouped + sorted (server-side if supported; else Python fallback)
        sort_col, sort_desc = _get_sort_params()
        try:
            entries = fetch_grouped_trades(sort_by=sort_col, sort_desc=sort_desc)
        except TypeError:
            entries = fetch_grouped_trades()
            entries = _python_sort_groups(entries, sort_col, sort_desc)

        entries = [e for e in entries if _is_display_entry(e)]
        _user, role = _current_user_and_role()

        return render_template(
            "ledger.html",
            entries=entries,
            error=None,
            balances=balances,
            coa_accounts=coa_accounts,
            coa_accounts_dropdown=coa_accounts_dropdown,
            coa_meta=coa_meta,
            user_role=role,
            has_unmapped=_has_unmapped(entries),
        )
    except FileNotFoundError:
        error = "Ledger database or table not found. Please initialize via admin tools."
    except Exception as e:
        error = f"Ledger error: {e}"
        traceback.print_exc()

    _user, role = _current_user_and_role()
    return render_template(
        "ledger.html",
        entries=[],
        error=error,
        balances={},
        coa_accounts=[],
        coa_accounts_dropdown=[],
        coa_meta={},
        user_role=role,
        has_unmapped=False,
    )


@ledger_web.route("/groups", methods=["GET"])
def ledger_groups():
    # RBAC: viewers allowed (GET)
    if provisioning_guard() or identity_guard():
        return jsonify({"error": "Not permitted"}), 403
    try:
        sort_col, sort_desc = _get_sort_params()
        try:
            groups = fetch_grouped_trades(sort_by=sort_col, sort_desc=sort_desc)
        except TypeError:
            groups = fetch_grouped_trades()
            groups = _python_sort_groups(groups, sort_col, sort_desc)
        groups = [g for g in groups if _is_display_entry(g)]
        return jsonify(groups)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@ledger_web.route("/balances", methods=["GET"])
def ledger_balances():
    # RBAC: viewers allowed (GET)
    if provisioning_guard() or identity_guard():
        return jsonify({"error": "Not permitted"}), 403
    try:
        try:
            bals = calculate_account_balances(include_opening=True)
        except TypeError:
            bals = calculate_account_balances()
        except Exception:
            bals = {}
        return jsonify(bals)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@ledger_web.route("/group/<group_id>", methods=["GET"])
def ledger_group_detail(group_id):
    # RBAC: viewers allowed (GET)
    if provisioning_guard() or identity_guard():
        return redirect(url_for("main.root_router"))
    try:
        group = fetch_trade_group_by_id(group_id)
        return jsonify(group)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@ledger_web.route("/collapse_expand/<group_id>", methods=["POST"])
def ledger_collapse_expand(group_id):
    # RBAC: admin-only for POST
    not_ok = _require_admin_post()
    if not_ok:
        return not_ok
    if provisioning_guard() or identity_guard():
        return jsonify({"ok": False, "error": "Not permitted"}), 403
    try:
        data = request.get_json(silent=True) or {}
        collapsed_state = data.get("collapsed_state", None)
        if collapsed_state is not None:
            collapsed_state = 1 if str(collapsed_state).lower() in ("1", "true", "yes") else 0
            result = collapse_expand_group(group_id, collapsed_state=collapsed_state)
        else:
            result = collapse_expand_group(group_id)
        return jsonify({"ok": True, "result": bool(result), "collapsed_state": collapsed_state})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ledger_web.route("/collapse_all", methods=["POST"])
def ledger_collapse_all():
    # RBAC: admin-only for POST
    not_ok = _require_admin_post()
    if not_ok:
        return not_ok
    if provisioning_guard() or identity_guard():
        return jsonify({"ok": False, "error": "Not permitted"}), 403
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

        # universal fetch with fallback signature
        try:
            groups = fetch_grouped_trades(collapse=True, limit=10000)
        except TypeError:
            groups = fetch_grouped_trades()

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


@ledger_web.route("/search", methods=["GET"])
def ledger_search():
    # RBAC: viewers allowed (GET)
    if provisioning_guard() or identity_guard():
        return jsonify({"error": "Not permitted"}), 403
    query = request.args.get("q", "").strip()
    sort_col, sort_desc = _get_sort_params()
    try:
        results = search_trades(search_term=query, sort_by=sort_col, sort_desc=sort_desc)
        results = [e for e in results if _is_display_entry(e)]
        return jsonify(results)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------- COA: JSON list for client-side dropdowns ----------
@ledger_web.route("/coa/accounts", methods=["GET"])
def coa_accounts_api():
    try:
        flat, dropdown, meta = _get_coa_lists()
        return jsonify({"accounts": flat, "accounts_dropdown": dropdown, "metadata": meta})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "accounts": [], "accounts_dropdown": [], "metadata": {}}), 500


# ---------- COA Mapping: soft alias to whatever blueprint is registered ----------
@ledger_web.route("/coa_mapping", methods=["GET"])
def alias_coa_mapping():
    """
    Provide a stable /coa_mapping URL even if the real mapping UI lives in another blueprint.
    Tries a set of likely endpoints; if none exist, returns a helpful 404 JSON.
    """
    candidates = [
        "coa_mapping_web.view_mapping",  # primary (new mapping UI)
        "coa_web.coa_mapping",           # legacy preferred
        "coa_web.index",                 # legacy fallback
        "settings_web.coa_mapping",
    ]
    for endpoint in candidates:
        try:
            url = url_for(endpoint)
            return redirect(url)
        except BuildError:
            continue
        except Exception:
            continue
    return jsonify({"error": "coa_mapping_ui_unavailable", "hint": "COA mapping UI blueprint not registered."}), 404


# ---------- Legacy resolve/add/edit/delete (admin-only POST) ----------
@ledger_web.route("/resolve/<int:entry_id>", methods=["POST"])
def resolve_ledger_entry(entry_id):
    not_ok = _require_admin_post()
    if not_ok:
        return not_ok
    if provisioning_guard() or identity_guard():
        return redirect(url_for("main.root_router"))
    from tbot_bot.accounting.ledger import mark_entry_resolved
    mark_entry_resolved(entry_id)
    flash("Entry marked as resolved.")
    return redirect(url_for("ledger_web.ledger_reconcile"))


@ledger_web.route("/add", methods=["POST"])
def add_ledger_entry_route():
    not_ok = _require_admin_post()
    if not_ok:
        return not_ok
    if provisioning_guard() or identity_guard():
        return redirect(url_for("main.root_router"))
    from tbot_bot.accounting.ledger import post_ledger_entries_double_entry

    form = request.form
    bot_identity = load_bot_identity()
    entity_code, jurisdiction_code, broker, bot_id = bot_identity.split("_")
    current_user, _role = _current_user_and_role()
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
        # Amount: non-null for double-entry helpers
        "amount": _num(form.get("total_value"), 0.0) or 0.0,
        # Minimal metadata so compliance filter won't choke
        "json_metadata": {},
        "raw_broker_json": {},
    }
    try:
        post_ledger_entries_double_entry([entry_data])
        flash("Ledger entry added (double-entry compliant).")
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: trades.trade_id" in str(e):
            flash("Trade ID already exists. Please use a unique Trade ID.", "error")
        else:
            flash(f"Ledger DB error: {e}", "error")
    except Exception as e:
        traceback.print_exc()
        flash(f"Ledger error: {e}", "error")
    return redirect(url_for("ledger_web.ledger_reconcile"))


@ledger_web.route("/edit/<int:entry_id>", methods=["POST"])
def ledger_edit(entry_id: int):
    """
    Minimal, audited COA reassignment endpoint used by inline dropdown.
    Body (JSON or form):
      - account_code: required, active COA code
      - reason: optional string
      - mapping write: mandatory

    Surgical tweak: pass a best-effort `event_type` to backend reassigner to
    satisfy NOT NULL audit_trail.event_type. If the backend signature doesn't
    accept it, gracefully fall back to the legacy call.
    """
    not_ok = _require_admin_post()
    if not_ok:
        return not_ok
    if provisioning_guard() or identity_guard():
        return jsonify({"ok": False, "error": "Not permitted"}), 403

    data = request.get_json(silent=True) or request.form or {}
    account_code = (data.get("account_code") or data.get("account") or "").strip()
    reason = (data.get("reason") or "").strip() or None
    if not _valid_account_code(account_code):
        return jsonify({"ok": False, "error": "invalid account code"}), 400

    user, _role = _current_user_and_role()
    actor = getattr(user, "username", None) or (user if user else "system")

    # Atomic reassignment with audit (reassign_leg_account handles auditing)
    try:
        _ensure_audit_trail_columns()
        from tbot_bot.accounting.ledger_modules.ledger_edit import reassign_leg_account

        EVENT_TYPE = "ledger.account.reassign"
        try:
            # Preferred path: newer backend that supports event_type kwarg
            result = reassign_leg_account(entry_id, account_code, actor, reason=reason, event_type=EVENT_TYPE)
        except TypeError as te:
            # Fallback: older backend without event_type kwarg
            # (Only fall back if the TypeError indicates an unexpected kwarg)
            msg = str(te)
            if "unexpected keyword argument 'event_type'" in msg or "positional arguments" in msg:
                result = reassign_leg_account(entry_id, account_code, actor, reason=reason)
            else:
                raise
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"reassign failed: {e}"}), 500

    # ALWAYS update mapping based on this reassignment (no shims, no toggles)
    mapping_ok = False
    try:
        from tbot_bot.accounting.coa_mapping_table import upsert_rule_from_leg as coa_upsert_rule_from_leg

        bot_identity = load_bot_identity()
        e, j, b, bot_id = bot_identity.split("_")
        db_path = resolve_ledger_db_path(e, j, b, bot_id)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            leg = conn.execute("SELECT * FROM trades WHERE id = ?", (entry_id,)).fetchone()

        if leg:
            # Strict helper signature: (leg: dict, account_code: str, actor: str)
            coa_upsert_rule_from_leg(dict(leg), account_code, actor)
            mapping_ok = True
    except Exception:
        traceback.print_exc()
        mapping_ok = False

    # Return fresh deltas for live UI
    try:
        sort_col, sort_desc = _get_sort_params()
        try:
            groups = fetch_grouped_trades(sort_by=sort_col, sort_desc=sort_desc)
        except TypeError:
            groups = fetch_grouped_trades()
            groups = _python_sort_groups(groups, sort_col, sort_desc)
        try:
            bals = calculate_account_balances(include_opening=True)
        except TypeError:
            bals = calculate_account_balances()
        except Exception:
            bals = {}
        return jsonify({"ok": True, "groups": groups, "balances": bals, "result": result, "mapping_ok": mapping_ok})
    except Exception:
        # minimal success if refresh fails
        return jsonify({"ok": True, "mapping_ok": mapping_ok})


@ledger_web.route("/edit_legacy/<int:entry_id>", methods=["POST"])
def edit_ledger_entry_route(entry_id):
    not_ok = _require_admin_post()
    if not_ok:
        return not_ok
    if provisioning_guard() or identity_guard():
        return redirect(url_for("main.root_router"))
    from tbot_bot.accounting.ledger import edit_ledger_entry

    form = request.form
    bot_identity = load_bot_identity()
    entity_code, jurisdiction_code, broker, bot_id = bot_identity.split("_")
    current_user, _role = _current_user_and_role()
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
        "amount": _num(form.get("total_value"), 0.0) or 0.0,
        "json_metadata": {},
        "raw_broker_json": {},
    }
    try:
        edit_ledger_entry(entry_id, updated_data)
        flash("Ledger entry updated.")
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: trades.trade_id" in str(e):
            flash("Trade ID already exists. Please use a unique Trade ID.", "error")
        else:
            flash(f"Ledger DB error: {e}", "error")
    except Exception as e:
        traceback.print_exc()
        flash(f"Ledger error: {e}", "error")
    return redirect(url_for("ledger_web.ledger_reconcile"))


@ledger_web.route("/delete/<int:entry_id>", methods=["POST"])
def delete_ledger_entry_route(entry_id):
    not_ok = _require_admin_post()
    if not_ok:
        return not_ok
    if provisioning_guard() or identity_guard():
        return redirect(url_for("main.root_router"))
    from tbot_bot.accounting.ledger import delete_ledger_entry
    delete_ledger_entry(entry_id)
    flash("Ledger entry deleted.")
    return redirect(url_for("ledger_web.ledger_reconcile"))


@ledger_web.route("/sync", methods=["POST"])
def ledger_sync():
    # RBAC: admin-only
    not_ok = _require_admin_post()
    if not_ok:
        return not_ok
    if provisioning_guard() or identity_guard():
        return redirect(url_for("main.root_router"))
    try:
        print("[WEB] /ledger/sync: invoked")
        # Use the new sync pipeline under ledger_modules
        from tbot_bot.accounting.ledger_modules.ledger_sync import sync_broker_ledger
        sync_broker_ledger()

        # post-check
        try:
            bot_identity = load_bot_identity()
            e, j, b, bot_id = bot_identity.split("_")
            db_path = resolve_ledger_db_path(e, j, b, bot_id)
            with sqlite3.connect(db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
                empty_groups = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE group_id IS NULL OR group_id=''"
                ).fetchone()[0]
            print(f"[WEB] /ledger/sync: completed OK - rows={total}, empty_group_id={empty_groups}")
            if total == 0:
                flash("Broker ledger sync completed, but no rows were imported. Check mapping and source data.", "error")
            elif empty_groups:
                flash(f"Broker ledger synced. {total} rows present; {empty_groups} missing group_id.")
            else:
                flash(f"Broker ledger synced successfully. {total} rows present.")
        except Exception as e2:
            print("[WEB] /ledger/sync: post-check failed:", repr(e2))
            flash("Broker ledger synced (post-check failed).")
    except Exception as e:
        traceback.print_exc()
        print("[WEB] /ledger/sync: ERROR:", repr(e))
        flash(f"Broker ledger sync failed: {e}", "error")
    return redirect(url_for("ledger_web.ledger_reconcile"))
