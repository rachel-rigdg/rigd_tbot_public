# tbot_bot/runtime/watchdog_bot.py
# Broker connectivity monitor and auto-shutdown (Single-Broker Mode)
# MUST ONLY BE LAUNCHED BY tbot_supervisor.py. Direct execution by CLI, main.py, or any other process is forbidden.

import sys

if __name__ == "__main__":
    print("[watchdog_bot.py] Direct execution is not permitted. This module must only be launched by tbot_supervisor.py.")
    sys.exit(1)

import time
import requests

def start_watchdog():
    from tbot_bot.config.env_bot import get_bot_config
    from tbot_bot.support.decrypt_secrets import decrypt_json
    from tbot_bot.support.utils_log import log_event
    from tbot_bot.trading.kill_switch import trigger_shutdown
    from tbot_bot.runtime.status_bot import update_bot_state

    config = get_bot_config()
    try:
        broker_creds = decrypt_json("broker_credentials")
    except Exception:
        broker_creds = {}

    BROKER_CODE = str(broker_creds.get("BROKER_CODE", "")).strip().lower()
    API_TIMEOUT = int(config.get("API_TIMEOUT", 3))

    def check_alpaca():
        base_url = broker_creds.get("BROKER_URL")
        api_key = broker_creds.get("BROKER_API_KEY")
        secret_key = broker_creds.get("BROKER_SECRET_KEY")

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
        health_url = broker_creds.get("BROKER_HOST")
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

    update_bot_state("monitoring")
    log_event("watchdog_bot", f"Starting broker connectivity check for \"{BROKER_CODE}\"")

    ok = False
    if BROKER_CODE == "alpaca":
        ok = check_alpaca()
    elif BROKER_CODE == "ibkr":
        ok = check_ibkr()
    else:
        log_event("watchdog_bot", f"Unsupported BROKER_CODE: \"{BROKER_CODE}\"")

    if not ok:
        update_bot_state("error")
        log_event("watchdog_bot", "Connectivity check failed — initiating shutdown.")
        trigger_shutdown(reason="Broker connectivity failure detected by watchdog")
    else:
        log_event("watchdog_bot", "Broker API connectivity OK")
