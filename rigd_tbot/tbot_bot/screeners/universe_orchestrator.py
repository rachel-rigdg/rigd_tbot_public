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
from typing import List, Dict, Any, Optional

from tbot_bot.support.path_resolver import (
    resolve_universe_partial_path,
    resolve_universe_cache_path,
    resolve_universe_log_path,
    get_output_path as _resolver_get_output_path,  # (surgical) expose passthrough for tests
)

from tbot_bot.screeners.screener_utils import get_universe_screener_secrets

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


# --- (surgical) Back-compat shim for tests: allow monkeypatching universe_orchestrator.get_output_path ---
def get_output_path(*args, **kwargs) -> str:
    """
    Thin passthrough to path_resolver.get_output_path so tests can monkeypatch
    universe_orchestrator.get_output_path directly (as they expect).
    """
    return _resolver_get_output_path(*args, **kwargs)
# --------------------------------------------------------------------------------------------------------


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


def _atomic_publish_text(text: str, out_path: str) -> None:
    """
    Atomically write text to out_path (used for NDJSON or simple text files).
    """
    dest_dir = os.path.dirname(out_path)
    os.makedirs(dest_dir, exist_ok=True)
    temp_path = out_path + ".staged.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, out_path)
    try:
        dir_fd = os.open(dest_dir, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        pass


def _stage_with_timestamp(partial_path: str) -> dict:
    """
    Read partial JSON and inject build_timestamp_utc, returning updated data (no write here).
    Accepts either:
      - JSON array of symbol dicts → wraps as {"symbols":[...]}
      - JSON object (already structured) → preserved
      - NDJSON (one JSON per line) → aggregated and wrapped as {"symbols":[...]}
    """
    with open(partial_path, "r", encoding="utf-8") as f:
        text = f.read().strip()

    payload: dict
    if not text:
        payload = {"symbols": []}
    else:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                payload = {"symbols": parsed}
            elif isinstance(parsed, dict):
                payload = dict(parsed)
            else:
                payload = {"symbols": []}
        except json.JSONDecodeError:
            # Fallback: NDJSON
            symbols: List[Any] = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    symbols.append(item)
                except Exception:
                    continue
            payload = {"symbols": symbols}

    ts = datetime.utcnow().isoformat() + "Z"
    # Do not overwrite existing fields except the timestamp we always set
    payload["build_timestamp_utc"] = ts
    return payload


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


def _final_payload_is_valid(data: dict) -> bool:
    """
    Minimal pre-publish validation:
      - dict required
      - either 'symbols' is a list OR 'status'=='waiting_for_credentials'
    """
    if not isinstance(data, dict):
        return False
    if "symbols" in data:
        return isinstance(data["symbols"], list)
    if data.get("status") == "waiting_for_credentials":
        return True
    return False


# =========================
# TEST-EXPECTED PUBLIC API
# =========================
def screener_creds_exist() -> bool:
    """
    Return True if universe screener credentials/config indicate a provider is set.
    Tests patch get_universe_screener_secrets(); we simply check returned keys.
    """
    # --- Fix 4.2.1: use utils and require normalized keys ---
    from tbot_bot.screeners import screener_utils  # local import to ease test monkeypatching
    try:
        c = screener_utils.get_universe_screener_secrets() or {}
        name_ok = bool((c.get("SCREENER_NAME") or "").strip())
        key_ok = bool((c.get("SCREENER_API_KEY") or "").strip())
        return bool(name_ok and key_ok)
    except Exception:
        return False


def fetch_broker_symbol_metadata_crash_resilient(
    *,
    env: Dict[str, Any],
    blocklist: List[str],
    exchanges: List[str],
    min_price: float,
    max_price: float,
    min_cap: float,
    max_cap: float,
    max_size: int,
) -> List[Dict[str, Any]]:
    """
    Dispatch to provider-specific staged fetcher based on SCREENER_NAME in env/secrets.
    Tests may patch provider fetchers on this module; attributes must exist.
    """
    # --- Fix 4.2.2: provider name fallback via utils ---
    name = (env.get("SCREENER_NAME") or "").upper().strip()
    if not name:
        from tbot_bot.screeners import screener_utils
        cfg = screener_utils.get_universe_screener_secrets() or {}
        name = (cfg.get("SCREENER_NAME") or "").upper().strip()

    # Map provider name → function attribute on this module
    provider_map = {
        "FINNHUB": fetch_finnhub_symbols_staged,
        "TRADIER": fetch_tradier_symbols_staged,
        "ALPACA": fetch_alpaca_symbols_staged,
    }
    fn = provider_map.get(name)
    if fn is None:
        raise RuntimeError(f"Unsupported or unset screener provider: {name or '<NONE>'}")

    return fn(
        env=env,
        blocklist=blocklist,
        exchanges=exchanges,
        min_price=min_price,
        max_price=max_price,
        min_cap=min_cap,
        max_cap=max_cap,
        max_size=max_size,
    )


# Provider fetcher placeholders (tests patch these symbols; they should exist)
def fetch_finnhub_symbols_staged(**kwargs) -> List[Dict[str, Any]]:  # pragma: no cover
    raise RuntimeError("fetch_finnhub_symbols_staged not implemented in orchestrator")


def fetch_tradier_symbols_staged(**kwargs) -> List[Dict[str, Any]]:  # pragma: no cover
    raise RuntimeError("fetch_tradier_symbols_staged not implemented in orchestrator")


def fetch_alpaca_symbols_staged(**kwargs) -> List[Dict[str, Any]]:  # pragma: no cover
    raise RuntimeError("fetch_alpaca_symbols_staged not implemented in orchestrator")


def write_partial(symbols: List[Dict[str, Any]]) -> None:
    """
    Write both partial (JSON array) and unfiltered (JSON array) atomically.
    Tests expect this to exist and populate both files.
    """
    # Normalize to list of dicts
    safe_syms: List[Dict[str, Any]] = []
    for s in symbols or []:
        safe_syms.append(dict(s) if isinstance(s, dict) else {"symbol": str(s)})

    # Write pretty JSON (partial) and unfiltered mirror for compatibility
    _atomic_publish_json(safe_syms, PARTIAL_PATH)
    _atomic_publish_json(safe_syms, UNFILTERED_PATH)


# --- Fix 4.2.3: add explicit write_unfiltered helper expected by tests ---
def write_unfiltered(symbols: List[Dict[str, Any]]):
    """
    Persist raw/unfiltered universe snapshot for diagnostics.
    """
    data = list(symbols or [])
    _atomic_publish_json(data, UNFILTERED_PATH)
    return str(UNFILTERED_PATH)


def append_to_blocklist(symbol: str, path: Optional[str] = None, reason: Optional[str] = None) -> None:
    """
    Append a symbol to blocklist file with optional reason.
    """
    # --- Fix 4.2.4: CSV format "SYMBOL,REASON" (no '#') ---
    sym = (symbol or "").strip().upper()
    if not sym:
        return
    bl_path = path or BLOCKLIST_PATH
    os.makedirs(os.path.dirname(bl_path), exist_ok=True)
    line = f"{sym},{reason}\n" if reason else f"{sym}\n"
    try:
        with open(bl_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # fall back to atomic rewrite if append fails
        existing = ""
        try:
            with open(bl_path, "r", encoding="utf-8") as f:
                existing = f.read()
        except Exception:
            existing = ""
        new_text = (existing.rstrip("\n") + ("\n" if existing else "")) + line
        _atomic_publish_text(new_text, bl_path)


# =========================
# Orchestration entrypoint
# =========================
def main():
    # Step 1: Build raw symbols file from provider API (single API call)
    rc = run_module("tbot_bot.screeners.symbol_universe_raw_builder", tolerate_rcs=(NO_PROVIDER_EXIT,))
    if rc == NO_PROVIDER_EXIT:
        log("No universe provider enabled; deferring until credentials are added.")
        # Emit waiting state ONLY if final is missing; otherwise preserve last-good.
        if not os.path.exists(FINAL_PATH):
            _write_waiting_status(FINAL_PATH)
        sys.exit(0)
    if rc != 0:
        # Preserve last-good by exiting without touching FINAL_PATH
        log("Raw builder failed; preserving last known good universe.")
        sys.exit(rc)

    # Step 2: Enrich, filter, blocklist, and build universe files from API adapters
    rc = run_module("tbot_bot.screeners.symbol_enrichment")
    if rc != 0:
        # ---- Failure marker + preserve last good (do NOT publish) ----
        try:
            uni_dir = Path(FINAL_PATH).parent
            uni_dir.mkdir(parents=True, exist_ok=True)
            (uni_dir / "universe_build.failed").write_text(
                f"{datetime.utcnow().isoformat()}Z\n", encoding="utf-8"
            )
            log("CRITICAL: Universe build enrichment failed; keeping last known good.")
        finally:
            pass
        sys.exit(rc)

    # Step 3: Finalize — inject timestamp and atomically publish staged -> final
    if not os.path.exists(PARTIAL_PATH):
        log(f"ERROR: Missing partial universe: {PARTIAL_PATH}")
        sys.exit(1)

    try:
        data = _stage_with_timestamp(PARTIAL_PATH)
        if not _final_payload_is_valid(data):
            log("ERROR: Final payload validation failed; refusing to publish.")
            sys.exit(4)
        _atomic_publish_json(data, FINAL_PATH)
        log(f"Universe orchestration completed successfully. Published {FINAL_PATH}")
    except Exception as e:
        log(f"ERROR: Failed to publish universe: {e}")
        sys.exit(3)

    # Step 4: Poll for blocklist/manual recovery flag
    if poll_blocklist_recovery():
        log("Blocklist/manual recovery event logged during universe orchestration.")


if __name__ == "__main__":
    main()
