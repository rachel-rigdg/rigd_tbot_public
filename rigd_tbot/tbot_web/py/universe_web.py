# tbot_web/py/universe_web.py
# Flask blueprint for universe cache inspection, search, export, and rebuild

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, Response, send_from_directory
from tbot_bot.screeners.symbol_universe_refresh import main as rebuild_main
from tbot_bot.screeners.screener_utils import load_universe_cache, UniverseCacheError
from tbot_bot.support.path_resolver import resolve_universe_cache_path, resolve_universe_partial_path
import csv
import io
import json
import os

universe_bp = Blueprint("universe", __name__, template_folder="../templates")

def get_symbols_and_source():
    # Prefer partial if it exists and is newer than main cache.
    main_path = resolve_universe_cache_path()
    partial_path = resolve_universe_partial_path()
    use_partial = False
    main_mtime = os.path.getmtime(main_path) if os.path.exists(main_path) else 0
    partial_mtime = os.path.getmtime(partial_path) if os.path.exists(partial_path) else 0
    try:
        if partial_mtime > main_mtime:
            with open(partial_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            symbols = data.get("symbols", [])
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

@universe_bp.route("/universe", methods=["GET", "POST"])
def universe_status():
    symbols, use_partial = get_symbols_and_source()
    cache_path = resolve_universe_partial_path() if use_partial else resolve_universe_cache_path()
    symbol_count = len(symbols)
    status_msg = f"Universe cache loaded: {symbol_count} symbols." if symbols else "Universe cache not loaded or empty."
    data_source_label = "Partial (in-progress)" if use_partial else "Final (complete)"
    # Search/filter
    search = request.args.get("search", "").upper()
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    filtered = [s for s in symbols if not search or search in s["symbol"].upper()]
    total_pages = max(1, (len(filtered) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start, end = (page-1)*per_page, page*per_page
    page_symbols = filtered[start:end]
    return render_template(
        "universe.html",
        cache_ok=bool(symbols),
        status_msg=status_msg,
        cache_path=cache_path,
        symbol_count=len(filtered),
        sample_symbols=page_symbols,
        search=search,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        data_source_label=data_source_label
    )

@universe_bp.route("/universe/rebuild", methods=["POST"])
def universe_rebuild():
    try:
        rebuild_main()
        flash("Universe cache rebuild complete.", "success")
    except Exception as e:
        flash(f"Universe cache rebuild failed: {e}", "error")
    return redirect(url_for("universe.universe_status"))

@universe_bp.route("/universe/export/<fmt>", methods=["GET"])
def universe_export(fmt):
    symbols, use_partial = get_symbols_and_source()
    if not symbols:
        flash("Universe cache not loaded.", "error")
        return redirect(url_for("universe.universe_status"))
    if fmt == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(symbols[0].keys()))
        writer.writeheader()
        writer.writerows(symbols)
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=symbol_universe.csv"}
        )
    elif fmt == "json":
        return Response(
            json.dumps(symbols, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment;filename=symbol_universe.json"}
        )
    else:
        flash("Unsupported export format.", "error")
        return redirect(url_for("universe.universe_status"))

@universe_bp.route('/static/output/<path:filename>')
def output_static(filename):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'tbot_bot', 'output'))
    return send_from_directory(base_dir, filename)

@universe_bp.route('/universe/status_message')
def universe_status_message():
    symbols, use_partial = get_symbols_and_source()
    symbol_count = len(symbols)
    status_msg = f"Universe cache loaded: {symbol_count} symbols." if symbols else "Universe cache not loaded or empty."
    return status_msg, 200, {'Content-Type': 'text/plain; charset=utf-8'}
