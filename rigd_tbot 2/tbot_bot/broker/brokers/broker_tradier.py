# tbot_bot/broker/broker_tradier.py
# Tradier broker adapter (single-mode, single-broker architecture, spec compliant)

import requests
from tbot_bot.trading.logs_bot import log_event

class TradierBroker:
    def __init__(self, env):
        """
        Initializes Tradier broker using credentials and endpoint from unified config.
        """
        self.api_key = env.get("BROKER_API_KEY", "")
        self.account_number = env.get("BROKER_ACCOUNT_NUMBER", "")
        self.base_url = env.get("BROKER_URL", "https://api.tradier.com/v1")
        self.broker_token = env.get("BROKER_TOKEN", "")
        self.headers = {
            "Authorization": f"Bearer {self.api_key or self.broker_token}",
            "Accept": "application/json"
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
            log_event("broker_tradier", f"Request failed: {e}")
            raise

    def get_account_info(self):
        return self._request("GET", f"/user/profile")

    def get_positions(self):
        data = self._request("GET", f"/accounts/{self.account_number}/positions")
        return data.get("positions", {}).get("position", [])

    def get_position(self, symbol):
        positions = self.get_positions()
        return next((p for p in positions if p.get("symbol") == symbol), None)

    def submit_order(self, order):
        """
        Places an order. Expected order dict keys:
        - symbol, qty, side, order_type
        """
        payload = {
            "class": "equity",
            "symbol": order["symbol"],
            "side": order["side"],
            "quantity": order["qty"],
            "type": order.get("order_type", "market"),
            "duration": "day"
        }
        return self._request("POST", f"/accounts/{self.account_number}/orders", data=payload)

    def cancel_order(self, order_id):
        return self._request("DELETE", f"/accounts/{self.account_number}/orders/{order_id}")

    def close_position(self, symbol):
        pos = self.get_position(symbol)
        if not pos:
            return {"message": f"No position to close for {symbol}"}
        side = "sell" if float(pos.get("quantity", 0)) > 0 else "buy"
        order = {
            "symbol": symbol,
            "qty": abs(float(pos.get("quantity", 0))),
            "side": side,
            "order_type": "market"
        }
        return self.submit_order(order)

    def is_market_open(self):
        status = self._request("GET", "/markets/clock")
        return status.get("clock", {}).get("state", "").lower() == "open"

    def self_check(self):
        try:
            profile = self.get_account_info()
            return "profile" in profile
        except Exception:
            return False

    def is_symbol_tradable(self, symbol):
        try:
            url = f"/markets/lookup"
            params = {"q": symbol}
            res = self._request("GET", url, params=params)
            securities = res.get("securities", {}).get("security", [])
            for sec in securities:
                if sec.get("symbol", "").upper() == symbol.upper():
                    return True
            return False
        except Exception:
            return False

    # ========== SPEC ENFORCEMENT BELOW ==========

    def supports_fractional(self, symbol):
        """
        Tradier does not support fractional trading for equities as of 2024, return False for all.
        """
        return False

    def get_min_order_size(self, symbol):
        """
        Tradier equities: minimum size = 1 share, no fractional.
        """
        return 1

    def download_trade_ledger_csv(self, start_date=None, end_date=None, output_path=None):
        """
        Downloads executed trades from Tradier and writes a deduplicated CSV to output_path.
        """
        params = {}
        if start_date:
            params["start"] = start_date
        if end_date:
            params["end"] = end_date
        trades = self._request("GET", f"/accounts/{self.account_number}/orders", params=params)
        orders = trades.get("orders", {}).get("order", [])
        seen = set()
        fieldnames = [
            "id", "symbol", "quantity", "side", "type", "status", "filled_quantity", "avg_fill_price", "created_at"
        ]
        rows = []
        for t in orders:
            order_id = t.get("id")
            if order_id in seen:
                continue
            seen.add(order_id)
            rows.append({
                "id": order_id,
                "symbol": t.get("symbol"),
                "quantity": t.get("quantity"),
                "side": t.get("side"),
                "type": t.get("type"),
                "status": t.get("status"),
                "filled_quantity": t.get("filled_quantity"),
                "avg_fill_price": t.get("avg_fill_price"),
                "created_at": t.get("created_at"),
            })
        if output_path:
            import csv
            with open(output_path, "w", newline="") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        else:
            import io
            output = io.StringIO()
            import csv
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            return output.getvalue()
