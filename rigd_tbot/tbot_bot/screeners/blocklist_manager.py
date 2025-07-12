# tbot_bot/screeners/blocklist_manager.py
# Centralized blocklist management for atomic symbol universe builds and daily maintenance.
# Handles dynamic append of blocklisted symbols (per enrichment/filter step) with reason and timestamp.

import os
import json
from datetime import datetime, timezone

from tbot_bot.support.path_resolver import resolve_screener_blocklist_path

BLOCKLIST_PATH = resolve_screener_blocklist_path()
BLOCKLIST_LOG_PATH = "tbot_bot/output/screeners/blocklist_ops.log"

def utc_now():
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def log_blocklist_event(event: str, details: dict = None):
    now = utc_now().isoformat()
    msg = f"[{now}] {event}"
    if details:
        try:
            msg += " | " + json.dumps(details, ensure_ascii=False)
        except Exception:
            msg += f" | [Unserializable details: {details}]"
    os.makedirs(os.path.dirname(BLOCKLIST_LOG_PATH), exist_ok=True)
    with open(BLOCKLIST_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def atomic_append_text(path: str, line: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line if line.endswith("\n") else line + "\n")

def load_blocklist(path: str = BLOCKLIST_PATH):
    """
    Returns blocklist as set of symbols.
    Each line: symbol|reason|timestamp (pipe-delimited).
    """
    blockset = set()
    if not os.path.isfile(path):
        return blockset
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 2)
            if parts:
                blockset.add(parts[0].upper())
    return blockset

def get_blocklist_entries(path: str = BLOCKLIST_PATH):
    """
    Returns list of blocklist dicts: [{"symbol": ..., "reason": ..., "timestamp": ...}]
    """
    entries = []
    if not os.path.isfile(path):
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                symbol, reason, timestamp = parts[:3]
            elif len(parts) == 2:
                symbol, reason = parts[:2]
                timestamp = ""
            elif len(parts) == 1:
                symbol = parts[0]
                reason = timestamp = ""
            else:
                continue
            entries.append({"symbol": symbol, "reason": reason, "timestamp": timestamp})
    return entries

def add_to_blocklist(symbol: str, reason: str = ""):
    now = utc_now().isoformat() + "Z"
    entry = f"{symbol.upper()}|{reason}|{now}"
    atomic_append_text(BLOCKLIST_PATH, entry)
    log_blocklist_event("Added to blocklist", {"symbol": symbol.upper(), "reason": reason, "timestamp": now})

def remove_from_blocklist(symbol: str):
    symbol = symbol.upper()
    entries = get_blocklist_entries()
    updated = [e for e in entries if e["symbol"].upper() != symbol]
    with open(BLOCKLIST_PATH, "w", encoding="utf-8") as f:
        for e in updated:
            f.write(f"{e['symbol']}|{e['reason']}|{e['timestamp']}\n")
    log_blocklist_event("Removed from blocklist", {"symbol": symbol})

def is_blocked(symbol: str) -> bool:
    return symbol.upper() in load_blocklist()

def get_blocklist_count() -> int:
    return len(load_blocklist())

def clear_blocklist():
    open(BLOCKLIST_PATH, "w", encoding="utf-8").close()
    log_blocklist_event("Blocklist cleared")
