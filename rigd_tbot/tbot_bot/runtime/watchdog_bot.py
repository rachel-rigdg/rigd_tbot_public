# tbot_bot/runtime/watchdog_bot.py
# Broker connectivity monitor and auto-shutdown (Single-Broker Mode)

import time
import requests
from tbot_bot.config.env_bot import env_config
from tbot_bot.support.utils_log import log_event   # UPDATED: from logging_utils
from tbot_bot.trading.kill_switch import trigger_shutdown

BROKER_NAME = env_config.get("BROKER_NAME", "").lower()
API_TIMEOUT = int(env_config.get("API_TIMEOUT", 3))

def check_alpaca():
    base_url = env_config.get("ALPACA_BASE_URL")
    api_key = env_config.get("ALPACA_API_KEY")
    secret_key = env_config.get("ALPACA_SECRET_KEY")

    log_event("watchdog_bot", f"Checking Alpaca at {base_url}")

    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key
    }

    try:
        resp = requests.get(f"{base_url}/v2/account", headers=headers, timeout=API_TIMEOUT)
        if resp.status_code == 200:
            log_event("watchdog_bot", "Alpaca API check passed")
            return True
        else:
            log_event("watchdog_bot", f"Alpaca API error {resp.status_code}: {resp.text}")
    except Exception as e:
        log_event("watchdog_bot", f"Alpaca API exception: {e}")
    return False

def check_ibkr():
    health_url = env_config.get("IBKR_HEALTH_URL")
    log_event("watchdog_bot", f"Checking IBKR at {health_url}")

    try:
        resp = requests.get(health_url, timeout=API_TIMEOUT)
        if resp.status_code == 200 and resp.json().get("isAuthenticated"):
            log_event("watchdog_bot", "IBKR API check passed")
            return True
        else:
            log_event("watchdog_bot", f"IBKR API failure {resp.status_code}: {resp.text}")
    except Exception as e:
        log_event("watchdog_bot", f"IBKR API exception: {e}")
    return False

def start_watchdog():
    log_event("watchdog_bot", f"Starting broker connectivity check for {BROKER_NAME.upper()}")

    ok = False
    if BROKER_NAME == "alpaca":
        ok = check_alpaca()
    elif BROKER_NAME == "ibkr":
        ok = check_ibkr()
    else:
        log_event("watchdog_bot", f"Unsupported BROKER_NAME: {BROKER_NAME}")

    if not ok:
        log_event("watchdog_bot", f"Connectivity check failed — initiating shutdown.")
        trigger_shutdown()
    else:
        log_event("watchdog_bot", "Broker API connectivity OK")

if __name__ == "__main__":
    start_watchdog()
