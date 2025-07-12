# tbot_bot/screeners/universe_orchestrator.py
# Orchestrates the full nightly universe build process by running:
# 1) symbol_universe_refresh.py (fetch symbols, write unfiltered universe)
# 2) symbol_enrichment.py (enrich, filter, blocklist, write final universe)
# Logs progress and errors.

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
    run_module("tbot_bot.screeners.symbol_universe_refresh")
    run_module("tbot_bot.screeners.symbol_enrichment")
    log("Universe orchestration completed successfully.")

if __name__ == "__main__":
    main()
