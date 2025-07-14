# tbot_web/py/universe_web.py
# Flask blueprint for universe cache and blocklist management per staged symbol universe spec.

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, Response, send_from_directory, current_app, jsonify
import subprocess
from tbot_bot.screeners.screener_utils import load_universe_cache, load_blocklist, UniverseCacheError, get_screener_secrets
from tbot_bot.screeners.blocklist_manager import (
    add_to_blocklist,
    remove_from_blocklist,
    load_blocklist as blocklist_manager_load,
    get_blocklist_count,
)
from tbot_bot.support.path_resolver import (
    resolve_universe_cache_path,
    resolve_universe_partial_path,
    resolve_screener_blocklist_path,
    resolve_universe_unfiltered_path,
)
from tbot_bot.support.secrets_manager import get_screener_credentials_path
import csv
import io
import json
import os

universe_bp = Blueprint("universe", __name__, template_folder="../templates")

UNFILTERED_PATH = resolve_universe_unfiltered_path()
BLOCKLIST_PATH = resolve_screener_blocklist_path()

def screener_creds_exist():
    creds_path = get_screener_credentials_path()
    return os.path.exists(creds_path)

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            items = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
            return items
    except Exception:
        return []

def get_symbols_and_source():
    main_path = resolve_universe_cache_path()
    partial_path = resolve_universe_partial_path()
    use_partial = False
    main_mtime = os.path.getmtime(main_path) if os.path.exists(main_path) else 0
    partial_mtime = os.path.getmtime(partial_path) if os.path.exists(partial_path) else 0
    try:
        if partial_mtime > main_mtime:
            symbols = load_json_file(partial_path)
            use_partial = True
        else:
            symbols = load_universe_cache()
            use_partial = False
    except UniverseCacheError:
        symbols = []
        use_partial = False
    except Exception:
        symbols = []
        use_partial = False
    return symbols, use_partial

def get_all_counts():
    unfiltered = load_json_file(UNFILTERED_PATH)
    partial = load_json_file(resolve_universe_partial_path())
    try:
        filtered = load_universe_cache()
    except Exception:
        filtered = []
    try:
        block_count = get_blocklist_count()
    except Exception:
        block_count = 0
    return {
        "unfiltered": len(unfiltered),
        "partial": len(partial),
        "filtered": len(filtered),
        "blocklist": block_count,
    }

@universe_bp.route("/", methods=["GET", "POST"])
def universe_status():
    unfiltered_symbols = load_json_file(UNFILTERED_PATH)
    partial_symbols = load_json_file(resolve_universe_partial_path())
    try:
        final_symbols = load_universe_cache()
    except Exception:
        final_symbols = []
    try:
        with open(BLOCKLIST_PATH, "r", encoding="utf-8") as bf:
            blocklist_entries = [line.strip() for line in bf if line.strip() and not line.startswith("#")]
    except Exception:
        blocklist_entries = []
    cache_path = resolve_universe_cache_path()
    status_msg = f"Universe cache loaded: {len(final_symbols)} symbols." if final_symbols else "Universe cache not loaded or empty."
    data_source_label = "Final (complete)"
    search = request.args.get("search", "").upper()
    creds_exists = screener_creds_exist()
    return render_template(
        "universe.html",
        unfiltered_symbols=unfiltered_symbols,
        partial_symbols=partial_symbols,
        final_symbols=final_symbols,
        blocklist_entries=blocklist_entries,
        cache_ok=bool(final_symbols),
        status_msg=status_msg if creds_exists else "Screener credentials not configured.",
        cache_path=cache_path,
        search=search,
        data_source_label=data_source_label,
        screener_creds_exist=creds_exists
    )

@universe_bp.route("/rebuild", methods=["POST"])
def universe_rebuild():
    if not screener_creds_exist():
        flash("Screener credentials not configured. Please configure screener credentials before building the universe.", "error")
        return redirect(url_for("universe.universe_status"))
    try:
        proc = subprocess.run(
            ["python3", "tbot_bot/screeners/universe_orchestrator.py"],
            capture_output=True,
            text=True
        )
        if proc.returncode != 0:
            flash(f"Universe cache rebuild failed: {proc.stderr}", "error")
        else:
            flash("Universe cache rebuild complete.", "success")
    except Exception as e:
        flash(f"Universe cache rebuild failed: {e}", "error")
    return redirect(url_for("universe.universe_status"))

@universe_bp.route("/export/<fmt>", methods=["GET"])
def universe_export(fmt):
    if not screener_creds_exist():
        flash("Screener credentials not configured. Please configure screener credentials before exporting.", "error")
        return redirect(url_for("universe.universe_status"))
    try:
        final_symbols = load_universe_cache()
    except Exception:
        final_symbols = []
    if not final_symbols:
        flash("Universe cache not loaded.", "error")
        return redirect(url_for("universe.universe_status"))
    if fmt == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(final_symbols[0].keys()))
        writer.writeheader()
        writer.writerows(final_symbols)
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=symbol_universe.csv"}
        )
    elif fmt == "json":
        return Response(
            json.dumps(final_symbols, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment;filename=symbol_universe.json"}
        )
    elif fmt == "blocklist":
        try:
            with open(BLOCKLIST_PATH, "r", encoding="utf-8") as bf:
                data = bf.read()
            return Response(
                data,
                mimetype="text/plain",
                headers={"Content-Disposition": "attachment;filename=screener_blocklist.txt"}
            )
        except Exception:
            flash("Blocklist file not found.", "error")
            return redirect(url_for("universe.universe_status"))
    else:
        flash("Unsupported export format.", "error")
        return redirect(url_for("universe.universe_status"))

@universe_bp.route('/static/output/screeners/<path:filename>')
def universe_output_static(filename):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'tbot_bot', 'output', 'screeners'))
    full_path = os.path.join(base_dir, filename)
    current_app.logger.debug(f"Serving universe static file: URL path='{filename}', full_path='{full_path}'")
    if not os.path.isfile(full_path):
        current_app.logger.warning(f"Universe static file not found: {full_path}")
    return send_from_directory(base_dir, filename)

@universe_bp.route('/status_message')
def universe_status_message():
    counts = get_all_counts()
    status_msg = (
        f"Unfiltered: {counts['unfiltered']} | Partial: {counts['partial']} | Filtered: {counts['filtered']} | Blocklist: {counts['blocklist']}"
        if sum(counts.values()) > 0 else
        "Universe files not loaded or empty."
    )
    current_app.logger.debug(f"Status message requested, returning: {status_msg}")
    return status_msg, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@universe_bp.route("/refilter", methods=["POST"])
def universe_refilter():
    if not screener_creds_exist():
        flash("Screener credentials not configured. Please configure screener credentials before filtering the universe.", "error")
        return redirect(url_for("universe.universe_status"))
    try:
        from tbot_bot.screeners.universe_refilter import main as refilter_main
        refilter_main()
        flash("Universe re-filtered (partial and final cache updated).", "success")
    except Exception as e:
        flash(f"Refilter failed: {e}", "error")
    return redirect(url_for("universe.universe_status"))

@universe_bp.route("/blocklist", methods=["GET", "POST"])
def universe_blocklist():
    if request.method == "POST":
        symbol = request.form.get("symbol", "").strip().upper()
        action = request.form.get("action", "add")
        reason = request.form.get("reason", "")
        if symbol:
            if action == "add":
                add_to_blocklist([symbol], reason=reason or "Manual add from UI")
                flash(f"Added {symbol} to blocklist.", "success")
            elif action == "remove":
                remove_from_blocklist([symbol], reason=reason or "Manual remove from UI")
                flash(f"Removed {symbol} from blocklist.", "success")
    blocklist = []
    try:
        with open(BLOCKLIST_PATH, "r", encoding="utf-8") as bf:
            blocklist = [line.strip() for line in bf if line.strip() and not line.startswith("#")]
    except Exception:
        blocklist = []
    return render_template(
        "blocklist.html",
        blocklist_entries=blocklist,
    )

@universe_bp.route("/table/<table_type>")
def universe_table_api(table_type):
    search = request.args.get("search", "").upper()
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 100))
    if table_type == "unfiltered":
        data = load_json_file(UNFILTERED_PATH)
    elif table_type == "partial":
        data = load_json_file(resolve_universe_partial_path())
    elif table_type == "final":
        try:
            data = load_universe_cache()
        except Exception:
            data = []
    elif table_type == "blocklist":
        try:
            with open(BLOCKLIST_PATH, "r", encoding="utf-8") as bf:
                data = [line.strip() for line in bf if line.strip() and not line.startswith("#")]
        except Exception:
            data = []
    else:
        return jsonify({"error": "Invalid table type"}), 400
    if search:
        data = [s for s in data if search in (s if isinstance(s, str) else s.get("symbol", "")).upper()]
    return jsonify(data[offset:offset+limit])

@universe_bp.route("/counts")
def universe_counts():
    return jsonify(get_all_counts())
