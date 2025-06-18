# tbot_web/py/universe_web.py
# Flask blueprint for universe cache inspection, search, export, and rebuild

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, Response
from tbot_bot.screeners.symbol_universe_refresh import main as rebuild_main
from tbot_bot.screeners.screener_utils import load_universe_cache, UniverseCacheError
from tbot_bot.support.path_resolver import resolve_universe_cache_path
import csv
import io
import json

universe_bp = Blueprint("universe", __name__, template_folder="../templates")

def get_symbols():
    try:
        return load_universe_cache()
    except UniverseCacheError:
        return []

@universe_bp.route("/universe", methods=["GET", "POST"])
def universe_status():
    symbols = get_symbols()
    cache_path = resolve_universe_cache_path()
    symbol_count = len(symbols)
    status_msg = f"Universe cache loaded: {symbol_count} symbols." if symbols else "Universe cache not loaded or empty."
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
    symbols = get_symbols()
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
