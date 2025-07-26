# tbot_bot/broker/utils/broker_request.py

import requests
from tbot_bot.support.utils_log import log_event

def safe_request(method, url, headers=None, json_data=None, params=None):
    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
            params=params,
            timeout=15
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return resp.text
    except Exception as e:
        log_event("broker_request", f"Request failed: {e} {method} {url}", level="error")
        raise
