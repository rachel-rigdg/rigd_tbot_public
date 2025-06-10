# tbot_web/py/ledger_web.py
import csv
import io
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from tbot_bot.accounting.ledger import (
    load_internal_ledger,
    mark_entry_resolved,
    add_ledger_entry,
    edit_ledger_entry,
    delete_ledger_entry
)

ledger_web = Blueprint("ledger_web", __name__)

def reconcile_ledgers(internal, broker):
    result = []
    broker_lookup = {(row['date'], row['symbol'], row['type'], row['amount']): True for row in broker}
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
    return render_template('ledger.html', entries=entries)

@ledger_web.route('/ledger/resolve/<int:entry_id>', methods=['POST'])
def resolve_ledger_entry(entry_id):
    mark_entry_resolved(entry_id)
    flash('Entry marked as resolved.')
    return redirect(url_for('ledger_web.ledger_reconcile'))

@ledger_web.route('/ledger/add', methods=['POST'])
def add_ledger_entry_route():
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
    delete_ledger_entry(entry_id)
    flash('Ledger entry deleted.')
    return redirect(url_for('ledger_web.ledger_reconcile'))
