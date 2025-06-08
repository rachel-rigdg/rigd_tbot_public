# tbot_bot/reporting/auto_backup.py
# Compresses and archives logs/ledgers after session end into /backups/

import os
import zipfile
from datetime import datetime
import shutil
from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.support.path_resolver import get_output_path

# Constants
BACKUP_DIR = "backups"
BOT_IDENTITY = get_bot_identity()

def get_timestamp():
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")

def ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)

def backup_ledgers():
    ensure_backup_dir()
    timestamp = get_timestamp()
    
    ledger_files = {
        "ledger": f"{BOT_IDENTITY}_BOT_ledger.db",
        "coa": f"{BOT_IDENTITY}_BOT_COA.db"
    }

    for label, filename in ledger_files.items():
        src = get_output_path("ledgers", filename)
        if os.path.exists(src):
            dest = os.path.join(BACKUP_DIR, f"{label}_{timestamp}.db")
            shutil.copy2(src, dest)
            print(f"[auto_backup] Backed up {label} ledger → {dest}")
        else:
            print(f"[auto_backup] Skipped missing ledger: {src}")

def zip_session_artifacts():
    ensure_backup_dir()
    timestamp = get_timestamp()
    zip_name = f"{BOT_IDENTITY}_session_backup_{timestamp}.zip"
    zip_path = os.path.join(BACKUP_DIR, zip_name)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Logs
        for log_file in ["open.log", "mid.log", "close.log", "unresolved_orders.log", "error_tracebacks.log"]:
            log_path = get_output_path("logs", log_file)
            if os.path.exists(log_path):
                zipf.write(log_path, arcname=f"logs/{log_file}")
        
        # Summaries
        summary_file = f"{BOT_IDENTITY}_BOT_daily_summary.json"
        summary_path = get_output_path("summaries", summary_file)
        if os.path.exists(summary_path):
            zipf.write(summary_path, arcname=f"summaries/{summary_file}")
        
        # Trades
        for ext in ["csv", "json"]:
            trade_file = f"{BOT_IDENTITY}_BOT_trade_history.{ext}"
            trade_path = get_output_path("trades", trade_file)
            if os.path.exists(trade_path):
                zipf.write(trade_path, arcname=f"trades/{trade_file}")

    print(f"[auto_backup] Session data archived → {zip_path}")

def run_auto_backup():
    print("[auto_backup] Starting session backup...")
    backup_ledgers()
    zip_session_artifacts()
    print("[auto_backup] Backup complete.")

if __name__ == "__main__":
    run_auto_backup()
