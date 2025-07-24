# tbot_web/py/ledger_web.py

import csv
import io
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from pathlib import Path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import validate_bot_identity, get_bot_identity_string_regex
from tbot_web.support.auth_web import get_current_user
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.accounting.ledger_utils import calculate_running_balances
from tbot_web.support.utils_coa_web import load_coa_metadata_and_accounts
import sqlite3

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

def reconcile_ledgers(internal, broker):
    result = []
    broker_lookup = {(row.get('datetime_utc'), row.get('symbol'), row.get('action'), row.get('total_value')) for row in broker}
    for entry in internal:
        key = (entry.get('datetime_utc'), entry.get('symbol'), entry.get('action'), entry.get('total_value'))
        if entry.get('resolved'):
            status = "resolved"
        elif key in broker_lookup:
            status = "ok"
        else:
            status = "mismatch"
        result.append({**entry, "status": status})
    return result

@ledger_web.route('/ledger/reconcile', methods=['GET', 'POST'])
def ledger_reconcile():
    error = None
    entries = []
    balances = {}
    coa_accounts = []
    if provisioning_guard() or identity_guard():
        return render_template('ledger.html', entries=entries, error="Ledger access not available (provisioning or identity incomplete).", balances=balances, coa_accounts=coa_accounts)
    try:
        from tbot_bot.accounting.ledger_utils import calculate_account_balances
        internal_ledger = calculate_running_balances()
        broker_entries = []
        entries = reconcile_ledgers(internal_ledger, broker_entries)
        balances = calculate_account_balances()
        # Correct: use utils_coa_web for account dropdowns/selections
        coa_data = load_coa_metadata_and_accounts()
        coa_accounts = [(acct["code"], acct["name"]) for acct in coa_data.get("accounts_flat", [])]
    except FileNotFoundError:
        error = "Ledger database or table not found. Please initialize via admin tools."
        entries = []
        balances = {}
        coa_accounts = []
    except Exception as e:
        error = f"Ledger error: {e}"
        entries = []
        balances = {}
        coa_accounts = []
    return render_template('ledger.html', entries=entries, error=error, balances=balances, coa_accounts=coa_accounts)

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
    entity_code, jurisdiction, broker, bot_id = bot_identity.split("_")
    current_user = get_current_user()
    config = get_bot_config()
    entry_data = {
        "datetime_utc": form.get("datetime_utc"),
        "symbol": form.get("symbol"),
        "action": form.get("action"),
        "quantity": form.get("quantity"),
        "price": form.get("price"),
        "total_value": form.get("total_value"),
        "fee": form.get("fee", 0.0),
        "account": form.get("account"),
        "strategy": form.get("strategy"),
        "trade_id": form.get("trade_id"),
        "tags": form.get("tags"),
        "notes": form.get("notes"),
        "jurisdiction": jurisdiction,
        "entity_code": entity_code,
        "language": config.get("LANGUAGE_CODE", "en"),
        "created_by": current_user.username if hasattr(current_user, "username") else (current_user if current_user else "system"),
        "updated_by": current_user.username if hasattr(current_user, "username") else (current_user if current_user else "system"),
        "approved_by": current_user.username if hasattr(current_user, "username") else (current_user if current_user else "system"),
        "approval_status": "pending",
        "gdpr_compliant": True,
        "ccpa_compliant": True,
        "pipeda_compliant": True,
        "hipaa_sensitive": False,
        "iso27001_tag": "",
        "soc2_type": "",
    }
    try:
        post_ledger_entries_double_entry([entry_data])
        flash('Ledger entry added (double-entry compliant).')
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: trades.trade_id" in str(e):
            flash("Trade ID already exists. Please use a unique Trade ID.", "error")
        else:
            flash(f"Ledger DB error: {e}", "error")
    except Exception as e:
        flash(f"Ledger error: {e}", "error")
    return redirect(url_for('ledger_web.ledger_reconcile'))

@ledger_web.route('/ledger/edit/<int:entry_id>', methods=['POST'])
def edit_ledger_entry_route(entry_id):
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    from tbot_bot.accounting.ledger import edit_ledger_entry
    form = request.form
    bot_identity = load_bot_identity()
    entity_code, jurisdiction, broker, bot_id = bot_identity.split("_")
    current_user = get_current_user()
    config = get_bot_config()
    updated_data = {
        "datetime_utc": form.get("datetime_utc"),
        "symbol": form.get("symbol"),
        "action": form.get("action"),
        "quantity": form.get("quantity"),
        "price": form.get("price"),
        "total_value": form.get("total_value"),
        "fee": form.get("fee", 0.0),
        "account": form.get("account"),
        "strategy": form.get("strategy"),
        "trade_id": form.get("trade_id"),
        "tags": form.get("tags"),
        "notes": form.get("notes"),
        "jurisdiction": jurisdiction,
        "entity_code": entity_code,
        "language": config.get("LANGUAGE_CODE", "en"),
        "updated_by": current_user.username if hasattr(current_user, "username") else (current_user if current_user else "system"),
        "approval_status": form.get("approval_status", "pending"),
        "gdpr_compliant": True,
        "ccpa_compliant": True,
        "pipeda_compliant": True,
        "hipaa_sensitive": False,
        "iso27001_tag": "",
        "soc2_type": "",
    }
    try:
        edit_ledger_entry(entry_id, updated_data)
        flash('Ledger entry updated.')
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: trades.trade_id" in str(e):
            flash("Trade ID already exists. Please use a unique Trade ID.", "error")
        else:
            flash(f"Ledger DB error: {e}", "error")
    except Exception as e:
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
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    try:
        from tbot_bot.accounting.ledger import sync_broker_ledger
        sync_broker_ledger()
        flash("Broker ledger synced successfully.")
    except Exception as e:
        flash(f"Broker ledger sync failed: {e}")
    return redirect(url_for('ledger_web.ledger_reconcile'))
