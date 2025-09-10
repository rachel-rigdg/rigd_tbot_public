# tbot_bot/screeners/universe_orchestrator.py
# Orchestrates the full nightly universe build process:
# 1) Runs symbol_universe_raw_builder.py to create symbol_universe.symbols_raw.json (single API call)
# 2) Runs symbol_enrichment.py to enrich, filter, blocklist, and build universe files from API adapters
# 3) Atomically copies staged JSON (with injected build_timestamp_utc) to symbol_universe.json
# 4) Optionally polls for blocklist/manual recovery and logs if triggered
# Logs progress and errors. No legacy TXT/CSV steps.

import subprocess
import sys
import os
import json
from tbot_bot.screeners.screener_utils import atomic_copy_file
from tbot_bot.support.path_resolver import (
    resolve_universe_partial_path,
    resolve_universe_cache_path,
)
from datetime import datetime, timezone
print(f"[LAUNCH] universe_orchestrator.py launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)

# --- Exported constants required by tests ---
PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()
# Derive unfiltered alongside partial (do not modify imports)
UNFILTERED_PATH = os.path.join(os.path.dirname(PARTIAL_PATH), "symbol_universe.unfiltered.json")
# Blocklist path constant (same base as UNFILTERED_PATH, default to output/screeners/screener_blocklist.txt)
BLOCKLIST_PATH = os.path.join(os.path.dirname(UNFILTERED_PATH), "screener_blocklist.txt")


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


def _stage_with_timestamp(partial_path: str, final_path: str) -> str:
    """
    Read partial JSON, inject build_timestamp_utc, write staged file next to FINAL,
    fsync, then return staged path. Final atomic publish is done via atomic_copy_file().
    """
    with open(partial_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    ts = datetime.utcnow().isoformat() + "Z"
    data["build_timestamp_utc"] = ts

    dest_dir = os.path.dirname(final_path)
    os.makedirs(dest_dir, exist_ok=True)
    staged_path = final_path + ".staged.tmp"
    with open(staged_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    return staged_path


def main():
    # Step 1: Build raw symbols file from provider API (single API call)
    run_module("tbot_bot.screeners.symbol_universe_raw_builder")

    # Step 2: Enrich, filter, blocklist, and build universe files from API adapters
    run_module("tbot_bot.screeners.symbol_enrichment")

    # Step 3: Finalize — inject timestamp and atomically publish staged -> final
    if not os.path.exists(PARTIAL_PATH):
        log(f"ERROR: Missing partial universe: {PARTIAL_PATH}")
        sys.exit(1)

    try:
        staged = _stage_with_timestamp(PARTIAL_PATH, FINAL_PATH)
        # Atomic publish to FINAL_PATH (.tmp + fsync + rename handled in helper)
        atomic_copy_file(staged, FINAL_PATH)
        try:
            os.remove(staged)
        except OSError:
            pass
        log(f"Universe orchestration completed successfully. Published {FINAL_PATH}")
    except Exception as e:
        log(f"ERROR: Failed to publish universe: {e}")
        sys.exit(2)

    # Step 4: Poll for blocklist/manual recovery flag
    if poll_blocklist_recovery():
        log("Blocklist/manual recovery event logged during universe orchestration.")


if __name__ == "__main__":
    main()
