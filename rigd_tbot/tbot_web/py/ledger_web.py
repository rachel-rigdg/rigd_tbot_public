# tbot_web/py/ledger_web.py

import csv
import io
import traceback
import sqlite3
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify

from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import validate_bot_identity, get_bot_identity_string_regex, resolve_ledger_db_path
from tbot_web.support.auth_web import get_current_user
from tbot_bot.config.env_bot import get_bot_config
from tbot_web.support.utils_coa_web import load_coa_metadata_and_accounts

from tbot_bot.accounting.ledger_modules.ledger_grouping import (
    fetch_grouped_trades,
    fetch_trade_group_by_id,
    collapse_expand_group,
)
from tbot_bot.accounting.ledger_modules.ledger_query import search_trades

# Useful for display sanity (not mutating here)
from tbot_bot.accounting.ledger_modules.ledger_balance import calculate_running_balances  # noqa: F401

ledger_web = Blueprint("ledger_web", __name__)

BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "tbot_bot" / "control" / "bot_state.txt"
INITIALIZE_STATES = ("initialize", "provisioning", "bootstrapping")


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


@ledger_web.route('/ledger/reconcile', methods=['GET', 'POST'])
def ledger_reconcile():
    error = None
    entries = []
    balances = {}
    coa_accounts = []
    if provisioning_guard() or identity_guard():
        return render_template(
            'ledger.html',
            entries=entries,
            error="Ledger access not available (provisioning or identity incomplete).",
            balances=balances,
            coa_accounts=coa_accounts,
        )
    try:
        from tbot_bot.accounting.ledger_modules.ledger_balance import calculate_account_balances
        balances = calculate_account_balances()

        coa_data = load_coa_metadata_and_accounts()
        coa_accounts = coa_data.get("accounts_flat", [])

        # Use grouped view by default (collapsed)
        entries = fetch_grouped_trades()
        entries = [e for e in entries if _is_display_entry(e)]

        # Helpful trace for troubleshooting UI emptiness
        print("LEDGER ENTRIES SERVED (count={}):".format(len(entries)))
        if entries:
            print("LEDGER SAMPLE (first entry):", entries[0])

    except FileNotFoundError:
        error = "Ledger database or table not found. Please initialize via admin tools."
        entries = []
        balances = {}
        coa_accounts = []
    except Exception as e:
        error = f"Ledger error: {e}"
        traceback.print_exc()
        entries = []
        balances = {}
        coa_accounts = []
    return render_template('ledger.html', entries=entries, error=error, balances=balances, coa_accounts=coa_accounts)


@ledger_web.route('/ledger/group/<group_id>', methods=['GET'])
def ledger_group_detail(group_id):
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    try:
        group = fetch_trade_group_by_id(group_id)
        return jsonify(group)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@ledger_web.route('/ledger/collapse_expand/<group_id>', methods=['POST'])
def ledger_collapse_expand(group_id):
    if provisioning_guard() or identity_guard():
        return jsonify({"error": "Not permitted"}), 403
    try:
        result = collapse_expand_group(group_id)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ledger_web.route('/ledger/search', methods=['GET'])
def ledger_search():
    if provisioning_guard() or identity_guard():
        return jsonify({"error": "Not permitted"}), 403
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
    from tbot_bot.accounting.ledger import mark_entry_resolved
    mark_entry_resolved(entry_id)
    flash('Entry marked as resolved.')
    return redirect(url_for('ledger_web.ledger_reconcile'))


@ledger_web.route('/ledger/add', methods=['POST'])
def add_ledger_entry_route():
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    from tbot_bot.accounting.ledger import post_ledger_entries_double_entry

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
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: trades.trade_id" in str(e):
            flash("Trade ID already exists. Please use a unique Trade ID.", "error")
        else:
            flash(f"Ledger DB error: {e}", "error")
    except Exception as e:
        traceback.print_exc()
        flash(f"Ledger error: {e}", "error")
    return redirect(url_for('ledger_web.ledger_reconcile'))


@ledger_web.route('/ledger/edit/<int:entry_id>', methods=['POST'])
def edit_ledger_entry_route(entry_id):
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    from tbot_bot.accounting.ledger import edit_ledger_entry

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
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: trades.trade_id" in str(e):
            flash("Trade ID already exists. Please use a unique Trade ID.", "error")
        else:
            flash(f"Ledger DB error: {e}", "error")
    except Exception as e:
        traceback.print_exc()
        flash(f"Ledger error: {e}", "error")
    return redirect(url_for('ledger_web.ledger_reconcile'))


@ledger_web.route('/ledger/delete/<int:entry_id>', methods=['POST'])
def delete_ledger_entry_route(entry_id):
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    from tbot_bot.accounting.ledger import delete_ledger_entry
    delete_ledger_entry(entry_id)
    flash('Ledger entry deleted.')
    return redirect(url_for('ledger_web.ledger_reconcile'))


@ledger_web.route('/ledger/sync', methods=['POST'])
def ledger_sync():
    """
    Kicks off broker->ledger sync. Adds verbose traces so we can see when it ran and what it did.
    """
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    try:
        print("[WEB] /ledger/sync: invoked")
        from tbot_bot.accounting.ledger import sync_broker_ledger
        sync_broker_ledger()
        # quick post-check for sanity & flash useful info
        try:
            bot_identity = load_bot_identity()
            e, j, b, bot_id = bot_identity.split("_")
            db_path = resolve_ledger_db_path(e, j, b, bot_id)
            with sqlite3.connect(db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
                empty_groups = conn.execute("SELECT COUNT(*) FROM trades WHERE group_id IS NULL OR group_id=''").fetchone()[0]
            print(f"[WEB] /ledger/sync: completed OK - rows={total}, empty_group_id={empty_groups}")
            if empty_groups:
                flash(f"Broker ledger synced. {total} rows present; {empty_groups} missing group_id.")
            else:
                flash(f"Broker ledger synced successfully. {total} rows present.")
        except Exception as e2:
            print("[WEB] /ledger/sync: post-check failed:", repr(e2))
            flash("Broker ledger synced (post-check failed).")
    except Exception as e:
        traceback.print_exc()
        print("[WEB] /ledger/sync: ERROR:", repr(e))
        flash(f"Broker ledger sync failed: {e}")
    return redirect(url_for('ledger_web.ledger_reconcile'))
