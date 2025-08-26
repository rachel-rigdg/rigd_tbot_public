# tbot_bot/support/build_check.py
# Self-check for schema/COA alignment at build/runtime startup; blocks on mismatch.

import os
import sys
import json
import sqlite3
from tbot_bot.support.path_resolver import (
    get_output_path,
    resolve_coa_db_path,
    resolve_coa_template_path
)
from tbot_bot.support.utils_identity import get_bot_identity

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def check_coa_db_vs_template():
    # Get identity components and paths
    bot_identity = get_bot_identity()
    try:
        entity, jurisdiction, broker, bot_id = bot_identity.split("_")
    except Exception:
        print(f"[ERROR] Invalid BOT_IDENTITY_STRING: {bot_identity}")
        sys.exit(1)

    coa_db_path = resolve_coa_db_path(entity, jurisdiction, broker, bot_id)
    coa_template_path = resolve_coa_template_path()

    if not os.path.isfile(coa_db_path):
        print(f"[ERROR] Missing COA DB: {coa_db_path}")
        sys.exit(1)
    if not os.path.isfile(coa_template_path):
        print(f"[ERROR] Missing COA template: {coa_template_path}")
        sys.exit(1)

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
    db_accounts = [json.loads(row[0]) for row in cursor.fetchall()]
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
            # Write placeholder files for logs/trades as needed
            if category == "logs":
                for fname in ["open.log", "mid.log", "close.log"]:
                    fpath = os.path.join(path, fname)
                    if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
                        with open(fpath, "w", encoding="utf-8") as f:
                            f.write("INIT\n")
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
                if not os.path.isfile(trade_csv) or os.path.getsize(trade_csv) == 0:
                    with open(trade_csv, "w", encoding="utf-8") as f:
                        f.write("strategy,ticker,side,entry_price,exit_price,PnL\n")
                        f.write("test,FAKE,buy,100.0,101.0,1.0\n")
    if missing:
        for p in missing:
            print(f"[ERROR] Missing required output directory: {p}")
        sys.exit(1)
    print("[build_check] Output directory structure OK and placeholder logs/trade files written.")

def main():
    print("=== TradeBot COA/Schema Build Check ===")
    check_output_structure_and_logs()
    check_coa_db_vs_template()
    print("[RESULT] Build/schema check PASSED. Safe to continue.")
    sys.exit(0)

if __name__ == "__main__":
    main()
