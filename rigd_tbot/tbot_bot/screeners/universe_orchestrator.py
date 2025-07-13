# tbot_bot/screeners/universe_orchestrator.py
# Orchestrates the full nightly universe build process:
# Runs symbol_enrichment.py (API/adapters only), no TXT or file-based symbol sources.
# Logs progress and errors. No legacy TXT/CSV steps.

import subprocess
import sys
from datetime import datetime

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

def main():
    # Step 1: Run symbol_enrichment to enrich, filter, blocklist, and build universe files from API adapters
    run_module("tbot_bot.screeners.symbol_enrichment")
    log("Universe orchestration completed successfully.")

if __name__ == "__main__":
    main()
