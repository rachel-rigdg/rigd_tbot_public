# tbot_bot/screeners/universe_orchestrator.py
# Orchestrates the full nightly universe build process:
# 1) Runs symbol_universe_raw_builder.py to create symbol_universe.symbols_raw.json (single API call)
# 2) Runs symbol_enrichment.py to enrich, filter, blocklist, and build universe files from API adapters
# 3) Atomically writes FINAL (symbol_universe.json): write .partial → fsync → os.replace (atomic publish)
# 4) Optionally polls for blocklist/manual recovery and logs if triggered
# Logs progress and errors to screen and to universe_ops.log via path_resolver. No daemon behavior.

import subprocess
import sys
import os
import json
from datetime import datetime, timezone
from pathlib import Path

from tbot_bot.support.path_resolver import (
    resolve_universe_partial_path,
    resolve_universe_cache_path,
    resolve_universe_log_path,
    get_output_path,
)

print(f"[LAUNCH] universe_orchestrator.py launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)

# --- Exported constants required by tests ---
PARTIAL_PATH = resolve_universe_partial_path()
FINAL_PATH = resolve_universe_cache_path()
UNIVERSE_LOG_PATH = resolve_universe_log_path()

# Derive unfiltered alongside partial (kept for compatibility with existing builders)
UNFILTERED_PATH = os.path.join(os.path.dirname(PARTIAL_PATH), "symbol_universe.unfiltered.json")
# Blocklist path constant (same base as UNFILTERED_PATH)
BLOCKLIST_PATH = os.path.join(os.path.dirname(UNFILTERED_PATH), "screener_blocklist.txt")

# Special meaning: raw-builder uses 2 to indicate "no provider enabled"
NO_PROVIDER_EXIT = 2


def _append_log(msg: str) -> None:
    """Append a line to universe_ops.log via path_resolver (best-effort)."""
    try:
        Path(UNIVERSE_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(UNIVERSE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def log(msg):
    now = datetime.utcnow().isoformat() + "Z"
    line = f"[{now}] {msg}"
    print(line, flush=True)
    _append_log(line)


def _write_job_stamp(status_text: str) -> None:
    """Write a one-line stamp: 'YYYY-MM-DDTHH:MM:SSZ OK|Failed' (best-effort)."""
    try:
        stamp_path = Path(get_output_path("stamps", "universe_rebuild_last.txt"))
        stamp_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        stamp_path.write_text(f"{ts} {status_text}", encoding="utf-8")
    except Exception:
        pass


def run_module(module_path, tolerate_rcs=()):
    """
    Run a module via -m. Return its exit code.
    If exit code is non-zero and not tolerated, log details.
    """
    log(f"Starting {module_path}...")
    proc = subprocess.run([sys.executable, "-m", module_path], capture_output=True, text=True)
    rc = proc.returncode
    if rc != 0 and rc not in tolerate_rcs:
        log(f"{module_path} failed with exit code {rc}")
        if proc.stdout:
            _append_log(proc.stdout.rstrip())
            print(proc.stdout, end="")
        if proc.stderr:
            _append_log(proc.stderr.rstrip())
            print(proc.stderr, file=sys.stderr, end="")
    else:
        suffix = " (tolerated)" if rc in tolerate_rcs and rc != 0 else ""
        log(f"{module_path} completed successfully{suffix}.")
    return rc


def poll_blocklist_recovery():
    """
    Poll for manual blocklist or recovery file (blocklist_recovery.flag) adjacent to universe logs.
    If present, log event and remove the flag to allow manual intervention.
    """
    flag_path = os.path.join(os.path.dirname(UNIVERSE_LOG_PATH), "blocklist_recovery.flag")
    if os.path.exists(flag_path):
        log(f"Blocklist recovery/manual intervention triggered via {flag_path}")
        try:
            os.remove(flag_path)
        except OSError:
            pass
        return True
    return False


def _atomic_publish_json(data: dict, final_path: str) -> None:
    """
    Atomically write JSON to final_path:
      - write to temp file in same dir
      - flush + fsync file
      - os.replace(temp, final) (atomic on same filesystem)
      - fsync directory for durability
    """
    dest_dir = os.path.dirname(final_path)
    os.makedirs(dest_dir, exist_ok=True)
    temp_path = final_path + ".staged.tmp"

    # Write staged content
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    # Atomic replace
    os.replace(temp_path, final_path)

    # Fsync directory entry
    try:
        dir_fd = os.open(dest_dir, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        # best-effort on platforms without O_DIRECTORY
        pass


def _stage_with_timestamp(partial_path: str) -> dict:
    """
    Read partial JSON and inject build_timestamp_utc, returning updated data (no write here).
    """
    with open(partial_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    ts = datetime.utcnow().isoformat() + "Z"
    data["build_timestamp_utc"] = ts
    return data


def _write_waiting_status(final_path: str):
    """
    Write a minimal universe cache file indicating we're waiting for credentials.
    """
    payload = {
        "build_timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "status": "waiting_for_credentials",
        "counts": {"raw": 0, "unfiltered": 0, "partial": 0, "final": 0},
        "message": "Enable at least one screener API provider and mark UNIVERSE_ENABLED."
    }
    _atomic_publish_json(payload, final_path)
    log(f"Wrote waiting-for-credentials status to {final_path}")


def main():
    # Step 1: Build raw symbols file from provider API (single API call)
    rc = run_module("tbot_bot.screeners.symbol_universe_raw_builder", tolerate_rcs=(NO_PROVIDER_EXIT,))
    if rc == NO_PROVIDER_EXIT:
        log("No universe provider enabled; deferring until credentials are added.")
        _write_waiting_status(FINAL_PATH)
        _write_job_stamp("Failed")
        sys.exit(0)
    if rc != 0:
        _write_job_stamp("Failed")
        sys.exit(rc)

    # Step 2: Enrich, filter, blocklist, and build universe files from API adapters
    rc = run_module("tbot_bot.screeners.symbol_enrichment")
    if rc != 0:
        _write_job_stamp("Failed")
        sys.exit(rc)

    # Step 3: Finalize — inject timestamp and atomically publish staged -> final
    if not os.path.exists(PARTIAL_PATH):
        log(f"ERROR: Missing partial universe: {PARTIAL_PATH}")
        _write_job_stamp("Failed")
        sys.exit(1)

    try:
        data = _stage_with_timestamp(PARTIAL_PATH)
        _atomic_publish_json(data, FINAL_PATH)
        log(f"Universe orchestration completed successfully. Published {FINAL_PATH}")
        _write_job_stamp("OK")
    except Exception as e:
        log(f"ERROR: Failed to publish universe: {e}")
        _write_job_stamp("Failed")
        sys.exit(3)

    # Step 4: Poll for blocklist/manual recovery flag
    if poll_blocklist_recovery():
        log("Blocklist/manual recovery event logged during universe orchestration.")


if __name__ == "__main__":
    main()
