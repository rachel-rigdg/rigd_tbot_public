# tbot_bot/enhancements/ticker_blocklist.py
# Prevents duplicate ticker trading in same session
# ------------------------------------------------------

import os
import json
from datetime import datetime
from tbot_bot.support.utils_log import log_debug, log_error
from tbot_bot.support.path_resolver import get_output_path

# Resolve blocklist file within output/enhancements
BLOCKLIST_FILE = os.path.join(get_output_path("enhancements", "ticker_blocklist.json"))

def load_blocklist():
    """
    Loads the current blocklist of traded tickers from disk.
    Returns a set of tickers traded during the current UTC date.
    """
    if not os.path.exists(BLOCKLIST_FILE):
        return set()

    try:
        with open(BLOCKLIST_FILE, "r") as f:
            data = json.load(f)
            today = datetime.utcnow().date().isoformat()
            return set(ticker.upper() for ticker in data.get(today, []))
    except Exception as e:
        log_error(f"[ticker_blocklist] Failed to load blocklist: {e}", module="ticker_blocklist")
        return set()

def save_blocklist(ticker):
    """
    Saves a new ticker to the blocklist for the current UTC date.
    """
    try:
        today = datetime.utcnow().date().isoformat()
        if os.path.exists(BLOCKLIST_FILE):
            with open(BLOCKLIST_FILE, "r") as f:
                data = json.load(f)
        else:
            data = {}

        tickers_today = set(t.upper() for t in data.get(today, []))
        tickers_today.add(ticker.upper())
        data[today] = list(tickers_today)

        os.makedirs(os.path.dirname(BLOCKLIST_FILE), exist_ok=True)
        with open(BLOCKLIST_FILE, "w") as f:
            json.dump(data, f, indent=2)

        log_debug(f"[ticker_blocklist] Added {ticker.upper()} to blocklist.", module="ticker_blocklist")
    except Exception as e:
        log_error(f"[ticker_blocklist] Failed to save ticker {ticker}: {e}", module="ticker_blocklist")

def is_ticker_blocked(ticker):
    """
    Checks if the given ticker has already been traded today.
    Returns True if it is on the blocklist.
    """
    blocklist = load_blocklist()
    return ticker.upper() in blocklist
