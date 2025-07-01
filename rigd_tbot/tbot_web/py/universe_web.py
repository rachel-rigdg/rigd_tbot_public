# tbot_web/py/universe_web.py
# Flask blueprint for universe cache inspection, search, export, rebuild, re-filter, and table APIs (unfiltered/partial/final).

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, Response, send_from_directory, current_app, jsonify
from tbot_bot.screeners.symbol_universe_refresh import main as rebuild_main
from tbot_bot.screeners.screener_utils import load_universe_cache, filter_symbols, load_blocklist, UniverseCacheError, get_screener_secrets
from tbot_bot.screeners.blocklist_manager import add_to_blocklist, remove_from_blocklist, load_blocklist as blocklist_manager_load
from tbot_bot.support.path_resolver import resolve_universe_cache_path, resolve_universe_partial_path
import csv
import io
import json
import os

universe_bp = Blueprint("universe", __name__, template_folder="../templates")

UNFILTERED_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'tbot_bot', 'output', 'screeners', 'symbol_universe.unfiltered.json'))

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "symbols" in data:
            return data["symbols"]
        elif isinstance(data, list):
            return data
        return []
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

def get_all_counts():
    unfiltered = load_json_file(UNFILTERED_PATH)
    partial = load_json_file(resolve_universe_partial_path())
    try:
        filtered = load_universe_cache()
    except Exception:
        filtered = []
    return {
        "unfiltered": len(unfiltered),
        "partial": len(partial),
        "filtered": len(filtered),
    }

@universe_bp.route("/", methods=["GET", "POST"])
def universe_status():
    unfiltered_symbols = load_json_file(UNFILTERED_PATH)
    partial_symbols = load_json_file(resolve_universe_partial_path())
    try:
        final_symbols = load_universe_cache()
    except Exception:
        final_symbols = []
    cache_path = resolve_universe_cache_path()
    status_msg = f"Universe cache loaded: {len(final_symbols)} symbols." if final_symbols else "Universe cache not loaded or empty."
    data_source_label = "Final (complete)"
    search = request.args.get("search", "").upper()
    return render_template(
        "universe.html",
        unfiltered_symbols=unfiltered_symbols,
        partial_symbols=partial_symbols,
        final_symbols=final_symbols,
        cache_ok=bool(final_symbols),
        status_msg=status_msg,
        cache_path=cache_path,
        search=search,
        data_source_label=data_source_label
    )

@universe_bp.route("/rebuild", methods=["POST"])
def universe_rebuild():
    try:
        rebuild_main()
        flash("Universe cache rebuild complete.", "success")
    except Exception as e:
        flash(f"Universe cache rebuild failed: {e}", "error")
    return redirect(url_for("universe.universe_status"))

@universe_bp.route("/export/<fmt>", methods=["GET"])
def universe_export(fmt):
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
        f"Unfiltered: {counts['unfiltered']} | Partial: {counts['partial']} | Filtered: {counts['filtered']}"
        if sum(counts.values()) > 0 else
        "Universe files not loaded or empty."
    )
    current_app.logger.debug(f"Status message requested, returning: {status_msg}")
    return status_msg, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@universe_bp.route("/refilter", methods=["POST"])
def universe_refilter():
    try:
        unfiltered = load_json_file(UNFILTERED_PATH)
        from tbot_bot.config.env_bot import load_env_bot_config
        env = load_env_bot_config()
        exchanges = [e.strip() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NYSE,NASDAQ").split(",")]
        min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 5))
        max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 100))
        min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 2_000_000_000))
        max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
        max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))
        blocklist_path = env.get("SCREENER_UNIVERSE_BLOCKLIST_PATH", None)
        blocklist = load_blocklist(blocklist_path)
        filtered = filter_symbols(
            symbols=unfiltered,
            exchanges=exchanges,
            min_price=min_price,
            max_price=max_price,
            min_market_cap=min_cap,
            max_market_cap=max_cap,
            blocklist=blocklist,
            max_size=max_size
        )
        # Blocklist management: add symbols failing price filter
        from tbot_bot.screeners.blocklist_manager import add_to_blocklist
        low_price_symbols = [s["symbol"] for s in unfiltered if "lastClose" in s and s["lastClose"] is not None and s["lastClose"] < min_price]
        if low_price_symbols:
            add_to_blocklist(low_price_symbols, reason=f"Refiltered: price < {min_price}")
        partial_path = resolve_universe_partial_path()
        with open(partial_path, "w", encoding="utf-8") as pf:
            json.dump({
                "schema_version": "1.0.0",
                "build_timestamp_utc": "",
                "symbols": filtered
            }, pf, indent=2)
        flash(f"Re-filtered universe. New partial count: {len(filtered)}", "success")
    except Exception as e:
        flash(f"Refilter failed: {e}", "error")
    return redirect(url_for("universe.universe_status"))

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
    else:
        return jsonify({"error": "Invalid table type"}), 400
    if search:
        data = [s for s in data if search in s.get("symbol", "").upper()]
    return jsonify(data[offset:offset+limit])

@universe_bp.route("/counts")
def universe_counts():
    return jsonify(get_all_counts())
