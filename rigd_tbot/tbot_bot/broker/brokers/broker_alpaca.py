# tbot_bot/broker/brokers/alpaca.py
# Alpaca broker adapter (single-mode, single-broker architecture)

import requests
import csv
import io
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event  # FIXED: use correct logger

class AlpacaBroker:
    def __init__(self, env):
        """
        Initializes Alpaca broker using credentials and endpoint from unified, agnostic config.
        """
        self.api_key = env.get("BROKER_API_KEY")
        self.secret_key = env.get("BROKER_SECRET_KEY")
        self.broker_token = env.get("BROKER_TOKEN", "")
        self.base_url = env.get("BROKER_URL")
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key
        }
        if self.broker_token:
            self.headers["Authorization"] = f"Bearer {self.broker_token}"

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
            log_event("broker_alpaca", f"Request failed: {e}", level="error")
            raise

    def get_account_info(self):
        return self._request("GET", "/v2/account")

    def get_positions(self):
        return self._request("GET", "/v2/positions")

    def get_position(self, symbol):
        try:
            return self._request("GET", f"/v2/positions/{symbol}")
        except Exception:
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
        except Exception:
            return False

    def download_trade_ledger_csv(self, start_date=None, end_date=None, output_path=None):
        """
        Downloads trades from Alpaca and writes a deduplicated CSV to output_path.
        """
        params = {"status": "filled", "limit": 1000}
        if start_date:
            params["after"] = start_date
        if end_date:
            params["until"] = end_date
        trades = self._request("GET", "/v2/orders", params=params)
        unique = {}
        for t in trades:
            unique[t["id"]] = t  # dedupe by broker trade ID

        fieldnames = [
            "id", "symbol", "qty", "filled_at", "side", "type", "status", "filled_qty", "filled_avg_price"
        ]
        rows = []
        for t in unique.values():
            rows.append({
                "id": t.get("id"),
                "symbol": t.get("symbol"),
                "qty": t.get("qty"),
                "filled_at": t.get("filled_at"),
                "side": t.get("side"),
                "type": t.get("type"),
                "status": t.get("status"),
                "filled_qty": t.get("filled_qty"),
                "filled_avg_price": t.get("filled_avg_price"),
            })
        if output_path:
            with open(output_path, "w", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        else:
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            return output.getvalue()

    def is_symbol_tradable(self, symbol):
        try:
            resp = self._request("GET", f"/v2/assets/{symbol}")
            return resp.get("tradable", False)
        except Exception:
            return False

    # ========== SPEC ENFORCEMENT BELOW ==========

    def supports_fractional(self, symbol):
        """
        Returns True if symbol is fractionable on Alpaca.
        """
        try:
            resp = self._request("GET", f"/v2/assets/{symbol}")
            return resp.get("fractionable", False)
        except Exception:
            return False

    def get_min_order_size(self, symbol):
        """
        Returns the min order size (float) for symbol. Fallback to 1.0 if unavailable.
        """
        try:
            resp = self._request("GET", f"/v2/assets/{symbol}")
            min_size = resp.get("min_order_size", None)
            if min_size is not None:
                try:
                    return float(min_size)
                except Exception:
                    return 1.0
            return 1.0
        except Exception:
            return 1.0
