# tbot_bot/screeners/blocklist_manager.py
# Centralized blocklist management for staged symbol universe builds and daily universe maintenance.
# 100% spec-compliant. Handles dynamic creation, updating, polling, and cleaning of the blocklist
# for symbols that fail core filters (e.g., price, exchange, permanent delisting).

import os
import json
from datetime import datetime, timezone
from typing import List, Set, Dict

from tbot_bot.support.path_resolver import resolve_screener_blocklist_path

BLOCKLIST_PATH = resolve_screener_blocklist_path()
BLOCKLIST_LOG_PATH = "tbot_bot/output/screeners/blocklist_ops.log"

def utc_now():
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def log_blocklist_event(event: str, details: dict = None):
    now = utc_now().isoformat()
    msg = f"[{now}] {event}"
    if details:
        msg += " | " + json.dumps(details)
    with open(BLOCKLIST_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def load_blocklist(path: str = BLOCKLIST_PATH) -> Dict[str, dict]:
    """Returns blocklist as dict {symbol: {"reason":..., "timestamp":...}}"""
    blocklist = {}
    if not os.path.isfile(path):
        return blocklist
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",", 2)
            symbol = parts[0].upper()
            reason = parts[1] if len(parts) > 1 else ""
            timestamp = parts[2] if len(parts) > 2 else ""
            blocklist[symbol] = {"reason": reason, "timestamp": timestamp}
    return blocklist

def save_blocklist(blocklist: Dict[str, dict], path: str = BLOCKLIST_PATH):
    """Save blocklist dict to file."""
    with open(path, "w", encoding="utf-8") as f:
        for sym, meta in sorted(blocklist.items()):
            reason = meta.get("reason", "")
            timestamp = meta.get("timestamp", "")
            f.write(f"{sym},{reason},{timestamp}\n")
    log_blocklist_event("Blocklist updated", {"count": len(blocklist)})

def add_to_blocklist(symbols: List[str], reason: str = ""):
    now = utc_now().isoformat()
    symbols = [s.upper() for s in symbols]
    blocklist = load_blocklist()
    before_count = len(blocklist)
    for s in symbols:
        blocklist[s] = {"reason": reason, "timestamp": now}
    save_blocklist(blocklist)
    log_blocklist_event("Added to blocklist", {"symbols": symbols, "reason": reason, "before": before_count, "after": len(blocklist)})

def remove_from_blocklist(symbols: List[str], reason: str = ""):
    now = utc_now().isoformat()
    symbols = [s.upper() for s in symbols]
    blocklist = load_blocklist()
    before_count = len(blocklist)
    for s in symbols:
        if s in blocklist:
            del blocklist[s]
    save_blocklist(blocklist)
    log_blocklist_event("Removed from blocklist", {"symbols": symbols, "reason": reason, "before": before_count, "after": len(blocklist)})

def update_blocklist_price_poll(price_map: dict, min_price: float):
    """
    Polls and removes symbols from the blocklist if price >= min_price.
    `price_map` should be {symbol: price}
    """
    blocklist = load_blocklist()
    remove_syms = [s for s, p in price_map.items() if p is not None and p >= min_price and s.upper() in blocklist]
    if remove_syms:
        remove_from_blocklist(remove_syms, reason=f"Moved above min price {min_price}")

def blocklist_for_universe_build(symbols: List[dict], min_price: float) -> Set[str]:
    """
    Build/update blocklist set during staged universe build.
    Any symbol with price < min_price or delisted/exchange mismatch is added.
    """
    block_syms = set()
    now = utc_now().isoformat()
    for entry in symbols:
        symbol = entry.get("symbol", "").upper()
        last_close = entry.get("lastClose", None)
        exch = entry.get("exchange", "")
        if last_close is None or last_close < min_price or exch not in ("NASDAQ", "NYSE"):
            block_syms.add(symbol)
    if block_syms:
        add_to_blocklist(list(block_syms), reason="Universe build price/exchange fail")
    return block_syms

def is_blocked(symbol: str) -> bool:
    return symbol.upper() in load_blocklist()

def get_blocklist_count() -> int:
    return len(load_blocklist())
