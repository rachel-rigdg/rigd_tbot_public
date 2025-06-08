# tbot_bot/broker/brokers/alpaca.py
# Alpaca broker adapter (single-mode, single-broker architecture)

import requests
from tbot_bot.support.utils_time import utc_now
from tbot_bot.trading.logs_bot import log_event

class AlpacaBroker:
    def __init__(self, env):
        """
        Initializes Alpaca broker using credentials and endpoint from .env_bot config.
        """
        self.api_key = env.get("BROKER_API_KEY")
        self.secret_key = env.get("BROKER_SECRET_KEY")
        self.base_url = env.get("BROKER_URL")
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key
        }

    def _request(self, method, endpoint, data=None, params=None):
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(
                method, url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log_event("broker_alpaca", f"Request failed: {e}")
            raise

    def get_account_info(self):
        return self._request("GET", "/v2/account")

    def get_positions(self):
        return self._request("GET", "/v2/positions")

    def get_position(self, symbol):
        try:
            return self._request("GET", f"/v2/positions/{symbol}")
        except:
            return None

    def submit_order(self, order):
        """
        Places an order. Expected order dict keys:
        - symbol, qty, side, order_type, strategy
        """
        payload = {
            "symbol": order["symbol"],
            "qty": order["qty"],
            "side": order["side"],
            "type": order.get("order_type", "market"),
            "time_in_force": "day",
            "extended_hours": False
        }
        return self._request("POST", "/v2/orders", data=payload)

    def cancel_order(self, order_id):
        return self._request("DELETE", f"/v2/orders/{order_id}")

    def close_position(self, symbol):
        return self._request("DELETE", f"/v2/positions/{symbol}")

    def get_clock(self):
        return self._request("GET", "/v2/clock")

    def is_market_open(self):
        clock = self.get_clock()
        return clock.get("is_open", False)

    def self_check(self):
        """
        Verifies account status for readiness.
        """
        try:
            account = self.get_account_info()
            return account.get("status", "").upper() == "ACTIVE"
        except:
            return False
