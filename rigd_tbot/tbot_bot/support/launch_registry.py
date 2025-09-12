# tbot_bot/support/launch_registry.py
"""
Central registry of launchable modules for TradeBot.

Why this file?
- We launch workers via `python -m <module>` (not filesystem paths). This stays
  stable even if files move.
- The supervisor (and any ops scripts) should resolve a friendly name
  ("status_bot") to a fully-qualified module ("tbot_bot.runtime.status_bot")
  from a single source of truth.

What you get:
- MODULE_IMPORTS: canonical friendly-name -> module path mapping
- ALIASES: optional synonyms -> canonical friendly-name
- NON_RESTARTABLE: modules the supervisor must NOT auto-restart (one-offs / short-lived)
- Helper functions:
    resolve_runtime_module(name)           -> str (module path; raises on unknown)
    list_runtime_modules()                 -> dict copy
    list_aliases()                         -> dict copy
    registry_info()                        -> dict {name: {"module": ..., "aliases": [...], "exists": bool}}
    is_registered(name_or_module)          -> bool
    module_exists(module_path)             -> bool (checks importability)
    normalize_target(name_or_module)       -> (friendly_name or None, module_path or None)
    build_launch_cmd(name_or_module, ...)  -> list argv for Popen
    spawn_module(name_or_module, ...)      -> subprocess.Popen  (injects TBOT_LAUNCHED_BY_SUPERVISOR=1)
    is_process_running(name_or_module)     -> bool (best-effort; uses psutil if available)
    kill_processes(name_or_module, ...)    -> int count (best-effort; uses psutil if available)

Notes:
- We avoid importing heavy modules; we only use importlib.util.find_spec to
  validate module paths (lightweight).
- If psutil is missing, singleton helpers degrade gracefully without blocking launches.
"""

from __future__ import annotations

import os
import sys
import subprocess
from typing import Dict, Tuple, Optional, List

try:
    import importlib.util as _importlib_util
except Exception:  # extremely rare
    _importlib_util = None  # type: ignore

try:
    import psutil  # type: ignore
    _HAVE_PSUTIL = True
except Exception:
    psutil = None  # type: ignore
    _HAVE_PSUTIL = False

# -----------------------------------------------------------------------------
# Canonical registry
# -----------------------------------------------------------------------------

MODULE_IMPORTS: Dict[str, str] = {
    # ---- runtime (always-on / utilities) ------------------------------------
    "status_bot":              "tbot_bot.runtime.status_bot",
    "watchdog_bot":            "tbot_bot.runtime.watchdog_bot",
    "sync_broker_ledger":      "tbot_bot.runtime.sync_broker_ledger",
    "ledger_snapshot":         "tbot_bot.runtime.ledger_snapshot",
    "symbol_universe_refresh": "tbot_bot.runtime.symbol_universe_refresh",  # optional/periodic

    # ---- trading -------------------------------------------------------------
    "risk_module":             "tbot_bot.trading.risk_module",
    "kill_switch":             "tbot_bot.trading.kill_switch",
    "holdings_manager":        "tbot_bot.trading.holdings_manager",

    # ---- reporting -----------------------------------------------------------
    "log_rotation":            "tbot_bot.reporting.log_rotation",
    "trade_logger":            "tbot_bot.reporting.trade_logger",
    "status_logger":           "tbot_bot.reporting.status_logger",

    # ---- screeners / universe -----------------------------------------------
    "universe_orchestrator":   "tbot_bot.screeners.universe_orchestrator",

    # ---- tests ---------------------------------------------------------------
    "integration_test_runner": "tbot_bot.test.integration_test_runner",
}

# Optional synonyms that some scripts/ops may use
ALIASES: Dict[str, str] = {
    # universe
    "universe_rebuild": "universe_orchestrator",
    "universe":         "universe_orchestrator",

    # sync/snapshot
    "broker_sync":      "sync_broker_ledger",
    "snapshot":         "ledger_snapshot",

    # reporting
    "status":           "status_logger",
    "trades":           "trade_logger",

    # runtime
    "statusbot":        "status_bot",
    "watchdog":         "watchdog_bot",

    # trading
    "risk":             "risk_module",
    "killswitch":       "kill_switch",
    "holdings":         "holdings_manager",
}

# Modules the supervisor must NOT auto-restart when they exit.
# This prevents tight restart loops for short-lived/one-off tasks.
NON_RESTARTABLE = {
    "universe_orchestrator",   # one-off rebuild
    "integration_test_runner", # launched by flags; do not auto-restart
    "risk_module",             # exits immediately; not a daemon
    "kill_switch",             # exits immediately; not a daemon
    "sync_broker_ledger",      # nightly one-off
    "ledger_snapshot",         # nightly one-off
}

# -----------------------------------------------------------------------------
# Registry utilities
# -----------------------------------------------------------------------------

def list_runtime_modules() -> Dict[str, str]:
    """Return a copy of the friendly-name -> module mapping."""
    return dict(MODULE_IMPORTS)

def list_aliases() -> Dict[str, str]:
    """Return a copy of alias -> canonical friendly-name mapping."""
    return dict(ALIASES)

def resolve_runtime_module(name: str) -> str:
    """
    Resolve a friendly name (or alias) to its module import path.
    Raises ValueError if unknown.
    """
    if not name:
        raise ValueError("[launch_registry] Empty target name.")
    key = name.strip()
    if key in MODULE_IMPORTS:
        return MODULE_IMPORTS[key]
    if key in ALIASES:
        return MODULE_IMPORTS[ALIASES[key]]
    raise ValueError(f"[launch_registry] Unknown launch target: {name}")

def is_registered(name_or_module: str) -> bool:
    """True if input is a known friendly name, alias, or a registered module path."""
    if not name_or_module:
        return False
    s = name_or_module.strip()
    if s in MODULE_IMPORTS or s in ALIASES:
        return True
    return s in MODULE_IMPORTS.values()

def _reverse_lookup_module(module_path: str) -> Optional[str]:
    """Return friendly name for a registered module path, if any."""
    for k, v in MODULE_IMPORTS.items():
        if v == module_path:
            return k
    return None

def module_exists(module_path: str) -> bool:
    """Lightweight check that a module path is importable."""
    if not module_path or _importlib_util is None:
        return False
    try:
        return _importlib_util.find_spec(module_path) is not None
    except Exception:
        return False

def normalize_target(name_or_module: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Best-effort normalization:
      - If friendly name/alias -> (friendly, module)
      - If registered module path -> (friendly, module)
      - If non-registered module path -> (None, module)
      - Otherwise -> (None, None)
    """
    if not name_or_module:
        return None, None
    s = name_or_module.strip()

    # friendly or alias
    if s in MODULE_IMPORTS:
        return s, MODULE_IMPORTS[s]
    if s in ALIASES:
        canon = ALIASES[s]
        return canon, MODULE_IMPORTS[canon]

    # module path?
    if "." in s and s.replace(".", "").replace("_", "").isalnum():
        if s in MODULE_IMPORTS.values():
            return _reverse_lookup_module(s), s
        # Non-registered but looks like a module path
        return None, s

    return None, None

def registry_info() -> Dict[str, dict]:
    """
    Diagnostic: { friendly: {"module": ..., "aliases": [...], "exists": bool} }
    """
    by_name = {}
    alias_reverse = {}
    for a, canon in ALIASES.items():
        alias_reverse.setdefault(canon, []).append(a)
    for name, mod in MODULE_IMPORTS.items():
        by_name[name] = {
            "module": mod,
            "aliases": alias_reverse.get(name, []),
            "exists": module_exists(mod),
        }
    return by_name

# -----------------------------------------------------------------------------
# Launch helpers
# -----------------------------------------------------------------------------

def _default_python_exe() -> str:
    """
    Choose a Python executable:
      1) $TBOT_PYTHON if set
      2) sys.executable if available
      3) fallback 'python3'
    """
    return os.environ.get("TBOT_PYTHON") or sys.executable or "python3"

def build_launch_cmd(
    name_or_module: str,
    python_exe: Optional[str] = None,
    unbuffered: bool = True,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """
    Build the argv list to launch a module via `python -m`.
    Accepts a friendly name/alias or a raw module path.
    """
    friendly, module_path = normalize_target(name_or_module)
    if module_path is None:
        raise ValueError(f"[launch_registry] Cannot resolve module for: {name_or_module}")

    exe = python_exe or _default_python_exe()
    argv = [exe]
    if unbuffered:
        argv.append("-u")
    argv += ["-m", module_path]
    if extra_args:
        argv += list(extra_args)
    return argv

def spawn_module(
    name_or_module: str,
    python_exe: Optional[str] = None,
    unbuffered: bool = True,
    extra_args: Optional[List[str]] = None,
    **popen_kwargs,
) -> subprocess.Popen:
    """
    Launch a module as a subprocess with `python -m`.
    Injects TBOT_LAUNCHED_BY_SUPERVISOR=1 so workers with direct-exec guards run.
    Returns the Popen object.
    """
    argv = build_launch_cmd(name_or_module, python_exe=python_exe, unbuffered=unbuffered, extra_args=extra_args)

    # Merge/augment environment: always mark supervised launch
    base_env = os.environ.copy()
    user_env = popen_kwargs.pop("env", None)
    if user_env:
        base_env.update(user_env)
    base_env["TBOT_LAUNCHED_BY_SUPERVISOR"] = "1"

    # Helpful tag for logs
    friendly, module_path = normalize_target(name_or_module)
    worker_name = friendly or (module_path.rsplit(".", 1)[-1] if module_path else "")
    if worker_name:
        base_env.setdefault("TBOT_WORKER_NAME", worker_name)

    # Defaults: inherit stdio unless explicitly overridden
    popen_kwargs.setdefault("stdout", None)
    popen_kwargs.setdefault("stderr", None)
    popen_kwargs["env"] = base_env

    print(f"[launch_registry] launching: {' '.join(argv)}", flush=True)
    return subprocess.Popen(argv, **popen_kwargs)

# -----------------------------------------------------------------------------
# Process helpers (best-effort; psutil optional)
# -----------------------------------------------------------------------------

def is_process_running(name_or_module: str) -> bool:
    """
    Rough singleton detector:
      - Checks for '-m <module>' or the short module name in process cmdlines.
      - If input is a friendly name/alias, it's resolved first.
      - Returns False if psutil is unavailable.
    """
    if not _HAVE_PSUTIL:
        return False

    _, module_path = normalize_target(name_or_module)
    if not module_path:
        return False
    short = module_path.rsplit(".", 1)[-1]

    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if f"-m {module_path}" in cmdline or f"-m {short}" in cmdline or (short + ".py") in cmdline:
                return True
        except Exception:
            continue
    return False

def kill_processes(name_or_module: str, timeout_sec: float = 3.0) -> int:
    """
    Best-effort termination of matching processes. Returns count terminated.
    - Tries terminate() then kill() after timeout.
    - No-op if psutil is unavailable or nothing matches.
    """
    if not _HAVE_PSUTIL:
        return 0

    _, module_path = normalize_target(name_or_module)
    if not module_path:
        return 0
    short = module_path.rsplit(".", 1)[-1]

    matches = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if f"-m {module_path}" in cmdline or f"-m {short}" in cmdline or (short + ".py") in cmdline:
                matches.append(proc)
        except Exception:
            continue

    count = 0
    for proc in matches:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=timeout_sec)
            except Exception:
                proc.kill()
            count += 1
        except Exception:
            continue
    return count

# -----------------------------------------------------------------------------
# Public exports
# -----------------------------------------------------------------------------

__all__ = [
    "MODULE_IMPORTS",
    "ALIASES",
    "NON_RESTARTABLE",
    "list_runtime_modules",
    "list_aliases",
    "resolve_runtime_module",
    "is_registered",
    "module_exists",
    "normalize_target",
    "registry_info",
    "build_launch_cmd",
    "spawn_module",
    "is_process_running",
    "kill_processes",
]
