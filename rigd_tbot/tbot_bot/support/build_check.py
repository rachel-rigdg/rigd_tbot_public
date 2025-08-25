# tbot_bot/support/build_check.py
# Self-check for schema/COA alignment at build/runtime startup; blocks on mismatch.

import os
import sys
import json
import sqlite3
from tbot_bot.support.path_resolver import (
    get_output_path,
    resolve_coa_db_path,
    resolve_coa_template_path,
    resolve_ledger_db_path,
    resolve_coa_mapping_json_path_identity,
)
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.accounting.coa_mapping_table import load_mapping_table


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _split_identity_or_exit(bot_identity: str):
    try:
        entity, jurisdiction, broker, bot_id = bot_identity.split("_")
        return entity, jurisdiction, broker, bot_id
    except Exception:
        print(f"[ERROR] Invalid BOT_IDENTITY_STRING: {bot_identity}")
        sys.exit(1)


def _can_open_sqlite(db_path: str) -> bool:
    try:
        if not os.path.isfile(db_path):
            return False
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA quick_check")
        conn.close()
        return True
    except Exception as e:
        print(f"[ERROR] SQLite open/check failed for {db_path}: {e}")
        return False


def check_ledger_and_coa_paths():
    """
    Verifies resolved ledger/COA paths are identity-scoped and usable.
    Ensures ledgers/ exists, attempts lazy-create of COA mapping table JSON if missing.
    """
    bot_identity = get_bot_identity()
    entity, jurisdiction, broker, bot_id = _split_identity_or_exit(bot_identity)

    # Ledger DB path (directory must exist; DB may or may not yet exist)
    ledger_db_path = resolve_ledger_db_path(entity, jurisdiction, broker, bot_id)
    ledger_dir = os.path.dirname(ledger_db_path)
    os.makedirs(ledger_dir, exist_ok=True)
    print(f"[build_check] ledger_dir: {ledger_dir}")
    if os.path.isfile(ledger_db_path):
        ok = _can_open_sqlite(ledger_db_path)
        print(f"[build_check] ledger_db_present: True, open_ok: {ok}, path: {ledger_db_path}")
        if not ok:
            print("[ERROR] Ledger DB exists but failed integrity/open check.")
            sys.exit(1)
    else:
        print(f"[build_check] ledger_db_present: False (path prepared), path: {ledger_db_path}")

    # COA DB path (must exist for strict COA check performed later)
    coa_db_path = resolve_coa_db_path(entity, jurisdiction, broker, bot_id)
    coa_dir = os.path.dirname(coa_db_path)
    os.makedirs(coa_dir, exist_ok=True)
    print(f"[build_check] coa_dir: {coa_dir}")
    if os.path.isfile(coa_db_path):
        ok = _can_open_sqlite(coa_db_path)
        print(f"[build_check] coa_db_present: True, open_ok: {ok}, path: {coa_db_path}")
        if not ok:
            print("[ERROR] COA DB exists but failed integrity/open check.")
            sys.exit(1)
    else:
        print(f"[build_check] coa_db_present: False (expected to be provisioned), path: {coa_db_path}")

    # COA mapping table JSON (lazy-create if missing)
    mapping_path = str(resolve_coa_mapping_json_path_identity(bot_identity))
    mapping_dir = os.path.dirname(mapping_path)
    os.makedirs(mapping_dir, exist_ok=True)
    need_create = (not os.path.isfile(mapping_path)) or (os.path.getsize(mapping_path) == 0)
    print(f"[build_check] coa_mapping_path: {mapping_path}, exists: {not need_create}")

    if need_create:
        print("[build_check] coa_mapping_table.json missing or empty — invoking lazy-create via load_mapping_table()")
        try:
            load_mapping_table()  # expected to create/populate default mapping for current identity
        except Exception as e:
            print(f"[ERROR] load_mapping_table() failed: {e}")
            sys.exit(1)
        # Re-check
        if (not os.path.isfile(mapping_path)) or (os.path.getsize(mapping_path) == 0):
            print(f"[ERROR] coa_mapping_table.json was not created at: {mapping_path}")
            sys.exit(1)
        print("[build_check] coa_mapping_table.json created.")

    print("[build_check] Ledger/COA path checks complete.")


def check_coa_db_vs_template():
    # Get identity components and paths
    bot_identity = get_bot_identity()
    entity, jurisdiction, broker, bot_id = _split_identity_or_exit(bot_identity)

    coa_db_path = resolve_coa_db_path(entity, jurisdiction, broker, bot_id)
    coa_template_path = resolve_coa_template_path()

    if not os.path.isfile(coa_db_path):
        print(f"[ERROR] Missing COA DB: {coa_db_path}")
        sys.exit(1)
    if not os.path.isfile(coa_template_path):
        print(f"[ERROR] Missing COA template: {coa_template_path}")
        sys.exit(1)

    print(f"[build_check] COA DB: {coa_db_path}")
    print(f"[build_check] COA template: {coa_template_path}")

    coa_template = load_json(coa_template_path)

    conn = sqlite3.connect(coa_db_path)
    cursor = conn.cursor()

    # Check metadata version
    cursor.execute("SELECT coa_version FROM coa_metadata LIMIT 1")
    db_version = cursor.fetchone()
    if not db_version:
        print("[ERROR] COA DB missing version in metadata")
        sys.exit(1)
    db_version = db_version[0]

    template_version = "v1.0.0"  # Should match what provisioning sets; update if necessary
    if db_version != template_version:
        print(f"[ERROR] COA version mismatch: DB={db_version}, Template={template_version}")
        sys.exit(1)

    # Check account count and compare JSON structure
    cursor.execute("SELECT account_json FROM coa_accounts")
    rows = cursor.fetchall()
    db_accounts = [json.loads(row[0]) for row in rows]
    conn.close()

    if len(db_accounts) != len(coa_template):
        print(f"[ERROR] COA account count mismatch: DB={len(db_accounts)}, Template={len(coa_template)}")
        sys.exit(1)

    # Field-by-field comparison
    for i, (db_acc, tmpl_acc) in enumerate(zip(db_accounts, coa_template)):
        if db_acc != tmpl_acc:
            print(f"[ERROR] COA account mismatch at index {i}:\nDB: {db_acc}\nTemplate: {tmpl_acc}")
            sys.exit(1)

    print("[build_check] COA DB matches template and version.")


def check_output_structure_and_logs():
    bot_identity = get_bot_identity()
    categories = ["logs", "trades", "summaries", "ledgers"]
    missing = []
    for category in categories:
        path = get_output_path(category=category, bot_identity=bot_identity, filename="", output_subdir=True)
        if not os.path.isdir(path):
            missing.append(path)
        else:
            print(f"[build_check] category_ready: {category}, path: {path}")
            # Write placeholder files for logs/trades as needed
            if category == "logs":
                for fname in ["open.log", "mid.log", "close.log"]:
                    fpath = os.path.join(path, fname)
                    if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
                        with open(fpath, "w", encoding="utf-8") as f:
                            f.write("INIT\n")
                        print(f"[build_check] wrote_placeholder: {fpath}")
            if category == "trades":
                # Ensure a dummy trade history JSON and CSV exist
                trade_json = os.path.join(path, f"{bot_identity}_BOT_trade_history.json")
                trade_csv = os.path.join(path, f"{bot_identity}_BOT_trade_history.csv")
                if not os.path.isfile(trade_json) or os.path.getsize(trade_json) == 0:
                    with open(trade_json, "w", encoding="utf-8") as f:
                        json.dump([{
                            "strategy": "test",
                            "ticker": "FAKE",
                            "side": "buy",
                            "entry_price": 100.0,
                            "exit_price": 101.0,
                            "PnL": 1.0
                        }], f)
                    print(f"[build_check] wrote_placeholder: {trade_json}")
                if not os.path.isfile(trade_csv) or os.path.getsize(trade_csv) == 0:
                    with open(trade_csv, "w", encoding="utf-8") as f:
                        f.write("strategy,ticker,side,entry_price,exit_price,PnL\n")
                        f.write("test,FAKE,buy,100.0,101.0,1.0\n")
                    print(f"[build_check] wrote_placeholder: {trade_csv}")
    if missing:
        for p in missing:
            print(f"[ERROR] Missing required output directory: {p}")
        sys.exit(1)
    print("[build_check] Output directory structure OK and placeholder logs/trade files written.")


def main():
    print("=== TradeBot COA/Schema Build Check ===")
    check_output_structure_and_logs()
    check_ledger_and_coa_paths()
    check_coa_db_vs_template()
    print("[RESULT] Build/schema check PASSED. Safe to continue.")
    sys.exit(0)


if __name__ == "__main__":
    main()
