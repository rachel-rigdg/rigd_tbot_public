# tbot_web/py/ledger_web.py
import csv
import io
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from pathlib import Path
from tbot_bot.support.decrypt_secrets import load_bot_identity
from tbot_bot.support.path_resolver import validate_bot_identity, get_bot_identity_string_regex

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
    broker_lookup = {(row['date'], row['symbol'], row['type'], row['amount']) for row in broker}
    for entry in internal:
        key = (entry['date'], entry['symbol'], entry['type'], entry['amount'])
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
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    try:
        from tbot_bot.accounting.ledger import load_internal_ledger  # Lazy import after provisioning
        internal_ledger = load_internal_ledger()
        broker_entries = []
        if request.method == 'POST' and 'broker_csv' in request.files:
            csv_file = request.files['broker_csv']
            csv_reader = csv.DictReader(io.StringIO(csv_file.stream.read().decode('utf-8')))
            broker_entries = list(csv_reader)
            session['broker_entries'] = broker_entries
        else:
            broker_entries = session.get('broker_entries', [])
        entries = reconcile_ledgers(internal_ledger, broker_entries)
    except FileNotFoundError:
        error = "Ledger database or table not found. Please initialize via admin tools."
        entries = []
    except Exception as e:
        error = f"Ledger error: {e}"
        entries = []
    return render_template('ledger.html', entries=entries, error=error)

@ledger_web.route('/ledger/resolve/<int:entry_id>', methods=['POST'])
def resolve_ledger_entry(entry_id):
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    from tbot_bot.accounting.ledger import mark_entry_resolved  # Lazy import
    mark_entry_resolved(entry_id)
    flash('Entry marked as resolved.')
    return redirect(url_for('ledger_web.ledger_reconcile'))

@ledger_web.route('/ledger/add', methods=['POST'])
def add_ledger_entry_route():
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    from tbot_bot.accounting.ledger import add_ledger_entry  # Lazy import
    form = request.form
    entry_data = {
        "date": form.get("date"),
        "symbol": form.get("symbol"),
        "type": form.get("type"),
        "amount": form.get("amount")
    }
    add_ledger_entry(entry_data)
    flash('Ledger entry added.')
    return redirect(url_for('ledger_web.ledger_reconcile'))

@ledger_web.route('/ledger/edit/<int:entry_id>', methods=['POST'])
def edit_ledger_entry_route(entry_id):
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    from tbot_bot.accounting.ledger import edit_ledger_entry  # Lazy import
    form = request.form
    updated_data = {
        "date": form.get("date"),
        "symbol": form.get("symbol"),
        "type": form.get("type"),
        "amount": form.get("amount")
    }
    edit_ledger_entry(entry_id, updated_data)
    flash('Ledger entry updated.')
    return redirect(url_for('ledger_web.ledger_reconcile'))

@ledger_web.route('/ledger/delete/<int:entry_id>', methods=['POST'])
def delete_ledger_entry_route(entry_id):
    if provisioning_guard() or identity_guard():
        return redirect(url_for('main.root_router'))
    from tbot_bot.accounting.ledger import delete_ledger_entry  # Lazy import
    delete_ledger_entry(entry_id)
    flash('Ledger entry deleted.')
    return redirect(url_for('ledger_web.ledger_reconcile'))
