# tbot_bot/screeners/universe_orchestrator.py
# Orchestrates the full nightly universe build process:
# 1) Runs symbol_universe_raw_builder.py to create symbol_universe.symbols_raw.json (single API call)
# 2) Runs symbol_enrichment.py to enrich, filter, blocklist, and build universe files from API adapters
# 3) Atomically copies partial.json to symbol_universe.json
# 4) Optionally polls for blocklist/manual recovery and logs if triggered
# Logs progress and errors. No legacy TXT/CSV steps.

import subprocess
import sys
import os
from datetime import datetime
from tbot_bot.screeners.screener_utils import atomic_copy_file
from tbot_bot.support.path_resolver import (
    resolve_universe_partial_path, resolve_universe_cache_path
)

def log(msg):
    now = datetime.utcnow().isoformat() + "Z"
    print(f"[{now}] {msg}")

def run_module(module_path):
    log(f"Starting {module_path}...")
    proc = subprocess.run([sys.executable, "-m", module_path], capture_output=True, text=True)
    if proc.returncode != 0:
        log(f"{module_path} failed with exit code {proc.returncode}")
        print(proc.stdout)
        print(proc.stderr)
        sys.exit(proc.returncode)
    log(f"{module_path} completed successfully.")

def poll_blocklist_recovery():
    """
    Poll for manual blocklist or recovery file (blocklist_recovery.flag).
    If present, log event and remove the flag to allow manual intervention.
    """
    from tbot_bot.support.path_resolver import resolve_blocklist_recovery_flag_path
    flag_path = resolve_blocklist_recovery_flag_path()
    if os.path.exists(flag_path):
        log(f"Blocklist recovery/manual intervention triggered via {flag_path}")
        os.remove(flag_path)
        return True
    return False

def main():
    # Step 1: Build raw symbols file from provider API (single API call)
    run_module("tbot_bot.screeners.symbol_universe_raw_builder")
    # Step 2: Enrich, filter, blocklist, and build universe files from API adapters
    run_module("tbot_bot.screeners.symbol_enrichment")
    # Step 3: Finalize - atomically copy partial.json to symbol_universe.json
    PARTIAL_PATH = resolve_universe_partial_path()
    FINAL_PATH = resolve_universe_cache_path()
    if not os.path.exists(PARTIAL_PATH):
        log(f"ERROR: Missing partial universe: {PARTIAL_PATH}")
        sys.exit(1)
    atomic_copy_file(PARTIAL_PATH, FINAL_PATH)
    log("Universe orchestration completed successfully.")

    # Step 4: Poll for blocklist/manual recovery flag
    if poll_blocklist_recovery():
        log("Blocklist/manual recovery event logged during universe orchestration.")

if __name__ == "__main__":
    main()
