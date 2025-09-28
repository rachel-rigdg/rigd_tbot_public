# tbot_bot/support/bot_state_manager.py
"""
Centralized, robust read/write manager for bot_state.txt.

Goals
-----
- Single source of truth for the bot's lifecycle state across the entire system.
- Safe, atomic writes (no partial lines), resilient reads, and minimal dependencies.
- Strict but practical validation of states (includes bootstrap-era values for compatibility).
- Optional, lightweight audit trail to logs/bot_state_history.log for observability.

Design notes
------------
- Path is resolved via tbot_bot.support.path_resolver.get_bot_state_path().
- Writes are atomic: write to a temp file in the same directory, then os.replace().
- States are normalized to lowercase single tokens (e.g., "running", "analyzing").
- "idle" is reserved for explicit Stop/Kill flows; other modules should not set it during normal operation.
  We do not hard-block setting "idle", but we log a caution when reason is missing or looks non-terminating.
- History lines are ISO8601 UTC stamps with state and optional reason.
"""

from __future__ import annotations

import os
import sys
import time
import errno
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Tuple

# NOTE: Avoid importing path_resolver at module import time to prevent circular imports.
# We'll lazy-import the needed functions inside helpers below.

# In-process lock to serialize concurrent threads in the same interpreter
_LOCK = threading.Lock()

# Acceptable states (normalized, lowercase). Includes bootstrap-era states for compatibility.
VALID_STATES = {
    # Core runtime lifecycle
    "running",
    "analyzing",
    "trading",
    "monitoring",
    "error",
    "stopped",
    "shutdown",
    "shutdown_triggered",
    "graceful_closing_positions",
    "emergency_closing_positions",
    # Operator-triggered terminal state (must be explicit)
    "idle",
    # Historical/bootstrap/provisioning phases (read/write compatibility)
    "initialize",
    "initializing",
    "provisioning",
    "bootstrapping",
    "registration",
}

# Setting "idle" should come ONLY from explicit Stop/Kill routes.
_IDLE_ALLOWED_REASONS = {
    "stop",
    "kill",
    "stop/kill",
    "operator_stop",
    "operator_kill",
    "shutdown",
    "shutdown_triggered",
    "test:clear",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_file() -> Path:
    # Lazy import to avoid circular dependency during bootstrap
    from tbot_bot.support.path_resolver import get_bot_state_path
    return Path(get_bot_state_path())


def _history_file() -> Path:
    # logs/bot_state_history.log (ensure dir exists); lazy import to avoid cycles
    from tbot_bot.support.path_resolver import get_output_path
    p = Path(get_output_path("logs", "bot_state_history.log"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _normalize_state(s: Optional[str]) -> str:
    if not s:
        return ""
    return str(s).strip().lower()


def _warn(msg: str) -> None:
    try:
        sys.stderr.write(f"[bot_state_manager] {msg}\n")
        sys.stderr.flush()
    except Exception:
        pass


def _ensure_parent_dir(p: Path) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"bot_state_manager: cannot create directory {p.parent}: {e}")


def _atomic_write_text(path: Path, content: str) -> None:
    """
    Atomic write: write to a temp file in the same directory and replace().
    """
    _ensure_parent_dir(path)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
    # Always end with a single newline, single line payload
    payload = (content.rstrip("\n") + "\n").encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_first_line(path: Path) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            line = f.readline()
            return line.strip() if line else None
    except FileNotFoundError:
        return None
    except Exception:
        # If file is temporarily unavailable or partially written, brief backoff and retry once
        time.sleep(0.01)
        try:
            with open(path, "r", encoding="utf-8") as f:
                line = f.readline()
                return line.strip() if line else None
        except Exception:
            return None


def _append_history(ts_utc: str, state: str, reason: Optional[str]) -> None:
    try:
        h = _history_file()
        line = f"{ts_utc} {state}"
        if reason:
            line += f" reason={reason}"
        line += "\n"
        with open(h, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # History must never block state writes
        pass


def get_state(default: str = "running") -> str:
    """
    Read current bot state from bot_state.txt.
    - Returns a lowercase token.
    - If missing or unreadable, returns `default` (defaults to 'running').
    - If the file contains an unknown token, returns it as-is (normalized).
    """
    path = _state_file()
    raw = _read_first_line(path)
    if not raw:
        return _normalize_state(default)
    return _normalize_state(raw)


def set_state(state: str, reason: Optional[str] = None) -> str:
    """
    Write a new bot state to bot_state.txt atomically.
    - `state` is normalized to lowercase single token.
    - Unknown states are rejected with ValueError (we fail fast).
    - "idle" is accepted, but a caution is logged unless `reason` clearly indicates Stop/Kill/Shutdown flows.
    - Returns the state that was written (normalized).
    """
    s = _normalize_state(state)
    if not s:
        raise ValueError("bot_state_manager.set_state: state is empty")
    if s not in VALID_STATES:
        raise ValueError(f"bot_state_manager.set_state: invalid state '{state}'. "
                         f"Allowed: {sorted(VALID_STATES)}")

    # Enforce Stop/Kill discipline for idle
    if s == "idle":
        r = _normalize_state(reason)
        if r not in _IDLE_ALLOWED_REASONS:
            _warn("Attempting to set 'idle' without an explicit Stop/Kill/Shutdown reason. "
                  "Proceeding, but this should ONLY come from Stop/Kill handlers.")

    # Write only the normalized state token to bot_state.txt (no inline comments)
    line = s
    with _LOCK:
        _atomic_write_text(_state_file(), line)
        _append_history(_utc_now_iso(), s, _normalize_state(reason))
    return s


def ensure_state(expected: Iterable[str]) -> Tuple[bool, str]:
    """
    Convenience helper: check if current state is in `expected` (iterable of tokens).
    Returns (ok, current_state).
    """
    cur = get_state()
    return (_normalize_state(cur) in {_normalize_state(e) for e in expected}, cur)


def wait_for_state(target: Iterable[str],
                   timeout_sec: float = 30.0,
                   poll_interval_sec: float = 0.25) -> Tuple[bool, str]:
    """
    Block until the current state is any of `target` (iterable), a timeout elapses, or
    an unrecoverable error occurs. Returns (reached, current_state).
    """
    deadline = time.time() + max(0.0, timeout_sec)
    target_set = {_normalize_state(t) for t in target}
    while True:
        cur = get_state()
        if _normalize_state(cur) in target_set:
            return True, cur
        if time.time() >= deadline:
            return False, cur
        time.sleep(poll_interval_sec)


__all__ = [
    "get_state",
    "set_state",
    "ensure_state",
    "wait_for_state",
    "VALID_STATES",
]
