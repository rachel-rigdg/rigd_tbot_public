# tbot_bot/runtime/watchdog_bot.py
# Broker connectivity monitor and auto-shutdown (Single-Broker Mode)
# MUST ONLY BE LAUNCHED BY tbot_supervisor.py. Direct execution by CLI, main.py, or any other process is forbidden.

import os
import sys

# Allow running under the supervisor, block direct CLI runs.
if __name__ == "__main__" and not os.environ.get("TBOT_LAUNCHED_BY_SUPERVISOR"):
    print("[watchdog_bot.py] Direct execution is not permitted. This module must only be launched by tbot_supervisor.py.")
    sys.exit(1)

import time
import requests


def start_watchdog():
    from datetime import datetime, timezone
    from tbot_bot.config.env_bot import get_bot_config
    from tbot_bot.support.decrypt_secrets import decrypt_json
    from tbot_bot.support.utils_log import log_event
    from tbot_bot.trading.kill_switch import trigger_shutdown
    from tbot_bot.runtime.status_bot import update_bot_state

    print(f"[LAUNCH] watchdog_bot.py launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)

    # Static config (interval + timeouts); credential changes are re-read each loop.
    cfg = get_bot_config()
    API_TIMEOUT = int(cfg.get("API_TIMEOUT", 3))
    INTERVAL_SEC = int(cfg.get("WATCHDOG_INTERVAL_SEC", 15))

    def check_alpaca(creds: dict) -> bool:
        base_url = creds.get("BROKER_URL")
        api_key = creds.get("BROKER_API_KEY")
        secret_key = creds.get("BROKER_SECRET_KEY")

        log_event("watchdog_bot", f"Checking Alpaca at {base_url}")

        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }

        try:
            resp = requests.get(f"{base_url}/v2/account", headers=headers, timeout=API_TIMEOUT)
            if resp.status_code == 200:
                log_event("watchdog_bot", "Alpaca API check passed")
                return True
            log_event("watchdog_bot", f"Alpaca API error {resp.status_code}: {resp.text}")
        except Exception as e:
            log_event("watchdog_bot", f"Alpaca API exception: {e}")
        return False

    def check_ibkr(creds: dict) -> bool:
        health_url = creds.get("BROKER_HOST")
        log_event("watchdog_bot", f"Checking IBKR at {health_url}")
        try:
            resp = requests.get(health_url, timeout=API_TIMEOUT)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    data = {}
                if data.get("isAuthenticated"):
                    log_event("watchdog_bot", "IBKR API check passed")
                    return True
            log_event("watchdog_bot", f"IBKR API failure {resp.status_code}: {resp.text}")
        except Exception as e:
            log_event("watchdog_bot", f"IBKR API exception: {e}")
        return False

    # Persistent monitoring loop
    while True:
        try:
            update_bot_state("monitoring")

            try:
                broker_creds = decrypt_json("broker_credentials") or {}
            except Exception:
                broker_creds = {}

            broker_code = str(broker_creds.get("BROKER_CODE", "")).strip().lower()

            if not broker_code:
                # No credentials yet — this is common on fresh boots. Defer politely.
                log_event("watchdog_bot", "No broker credentials configured yet; deferring watchdog check.")
                time.sleep(INTERVAL_SEC)
                continue

            ok = False
            if broker_code == "alpaca":
                ok = check_alpaca(broker_creds)
            elif broker_code == "ibkr":
                ok = check_ibkr(broker_creds)
            else:
                # Unknown/unsupported broker code — don't hard-fail the system.
                log_event("watchdog_bot", f"Unsupported BROKER_CODE: \"{broker_code}\"; deferring check.")
                time.sleep(INTERVAL_SEC)
                continue

            if not ok:
                update_bot_state("error")
                log_event("watchdog_bot", "Connectivity check failed — initiating shutdown.")
                trigger_shutdown(reason="Broker connectivity failure detected by watchdog")
                # Give supervisor time to observe state/flags; avoid tight loop.
                time.sleep(INTERVAL_SEC)
            else:
                log_event("watchdog_bot", "Broker API connectivity OK")
                time.sleep(INTERVAL_SEC)

        except Exception as e:
            # Never crash the watchdog; log and retry.
            from tbot_bot.support.utils_log import log_event as _log
            _log("watchdog_bot", f"Unhandled exception in watchdog loop: {e}")
            time.sleep(INTERVAL_SEC)


# When launched with `-m` by the supervisor, run the watchdog.
if __name__ == "__main__":
    # At this point the env gate above has allowed us to run.
    start_watchdog()
