# tbot_bot/screeners/symbol_universe_raw_builder.py
# Stage 1: Downloads the full raw symbol universe via a single provider API call.
# Writes the complete raw symbol payload to symbol_universe.symbols_raw.json (newline-delimited JSON).
# All operations are atomic, crash-resumable, and audit-logged.
# No filtering, no enrichment, no blocklist applied here.

import os
import sys
import json
from datetime import datetime, timezone
from tbot_bot.support.secrets_manager import load_screener_credentials
from tbot_bot.support.path_resolver import resolve_universe_raw_path, resolve_universe_log_path
from tbot_bot.screeners.provider_registry import get_provider_class

RAW_PATH = resolve_universe_raw_path()
LOG_PATH = resolve_universe_log_path()

# Distinct exit codes so the orchestrator can treat ONLY 2 as "no provider yet"
NO_PROVIDER_EXIT = 2       # no enabled API provider / TXT-only configured
MISCONFIG_EXIT   = 3       # provider name present but no class mapping
FETCH_FAIL_EXIT  = 4       # provider.fetch_symbols() raised
EMPTY_EXIT       = 5       # provider returned 0 symbols

print(f"[LAUNCH] symbol_universe_raw_builder.py @ {datetime.now(timezone.utc).isoformat()}", flush=True)

def log_progress(msg, details=None):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    except Exception:
        pass
    now = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    record = f"[{now}] {msg}"
    if details is not None:
        try:
            record += " | " + json.dumps(details, ensure_ascii=False)
        except Exception:
            record += " | (details serialization failed)"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as logf:
            logf.write(record + "\n")
    except Exception:
        # never crash on logging
        pass

def _atomic_write_ndjson(lines, out_path: str) -> None:
    """
    Atomically write NDJSON:
      - write temp file
      - fsync file
      - os.replace
      - fsync directory entry
    """
    tmp_path = out_path + ".tmp"
    dest_dir = os.path.dirname(out_path)
    os.makedirs(dest_dir, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, out_path)
    try:
        dir_fd = os.open(dest_dir, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        pass

def get_raw_provider_creds():
    all_creds = load_screener_credentials() or {}
    provider_indices = []
    for k, v in all_creds.items():
        if k.startswith("PROVIDER_"):
            idx = k.split("_")[-1]
            universe_enabled = str(all_creds.get(f"UNIVERSE_ENABLED_{idx}", "")).strip().lower()
            screener_name = str(all_creds.get(f"SCREENER_NAME_{idx}", "")).strip()
            if universe_enabled == "true" and screener_name and not screener_name.upper().endswith("_TXT"):
                provider_indices.append(idx)

    if not provider_indices:
        raise RuntimeError(
            "No valid universe provider enabled. Enable at least one API provider (not *_TXT) "
            "in the credential admin with UNIVERSE_ENABLED checked."
        )

    idx = provider_indices[0]
    # Normalize to unsuffixed keys for downstream use
    return {
        key.replace(f"_{idx}", ""): v
        for key, v in all_creds.items()
        if key.endswith(f"_{idx}") and not key.startswith("PROVIDER_")
    }

def main():
    log_progress("symbol_universe_raw_builder.py started")
    try:
        screener_secrets = get_raw_provider_creds()
    except RuntimeError as e:
        # This is the ONLY path that should return NO_PROVIDER_EXIT (2)
        log_progress("No valid universe provider enabled. Aborting raw build.", {"error": str(e)})
        print(f"ERROR: {e}", flush=True)
        sys.exit(NO_PROVIDER_EXIT)
    except Exception as e:
        log_progress("Failed to read screener credentials.", {"error": str(e)})
        print(f"ERROR: failed to read screener credentials: {e}", flush=True)
        sys.exit(MISCONFIG_EXIT)

    name = (screener_secrets.get("SCREENER_NAME") or "").strip().upper()
    if name.endswith("_TXT"):
        # TXT providers are not valid sources for a raw universe build
        log_progress("TXT provider configured; aborting raw build.", {"provider": name})
        print(f"ERROR: TXT providers (like {name}) cannot be used for universe build. Enable a data API provider.", flush=True)
        sys.exit(NO_PROVIDER_EXIT)

    ProviderClass = get_provider_class(name)
    if ProviderClass is None:
        log_progress("No provider class mapping found.", {"provider": name})
        print(f"ERROR: No provider class mapping found for SCREENER_NAME '{name}'", flush=True)
        sys.exit(MISCONFIG_EXIT)

    provider = ProviderClass(screener_secrets)
    try:
        raw_symbols = provider.fetch_symbols()
    except Exception as e:
        log_progress("Provider fetch_symbols() failed, aborting.", {"error": str(e)})
        print(f"ERROR: fetch_symbols failed: {e}", flush=True)
        sys.exit(FETCH_FAIL_EXIT)

    if not raw_symbols:
        log_progress("Provider returned no symbols.")
        print("ERROR: provider returned no symbols.", flush=True)
        sys.exit(EMPTY_EXIT)

    # Ensure symbols are serializable lines before any write
    lines = []
    count = 0
    for s in raw_symbols:
        try:
            lines.append(json.dumps(s, ensure_ascii=False))
            count += 1
        except Exception as e:
            # skip un-serializable entries (do not write partial files)
            log_progress("Skipping non-serializable symbol entry.", {"error": str(e)})

    if count == 0:
        log_progress("All entries were non-serializable; nothing to write.", {"provider": name})
        print("ERROR: no serializable symbols to write.", flush=True)
        sys.exit(EMPTY_EXIT)

    _atomic_write_ndjson(lines, RAW_PATH)

    log_progress("Raw symbol universe written", {"raw_path": RAW_PATH, "count": count, "provider": name})
    print(f"Raw symbol universe build complete: {count} symbols written to {RAW_PATH}", flush=True)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log_progress("Raw universe build failed and raised exception", {"error": str(e)})
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)
