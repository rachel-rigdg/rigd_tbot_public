# tbot_bot/broker/adapters/tradier.py

import hashlib
from tbot_bot.broker.core.broker_interface import BrokerInterface
from tbot_bot.broker.utils.broker_request import safe_request
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade

class TradierBroker(BrokerInterface):
    def __init__(self, env):
        self.base_url = env.get("BROKER_URL")
        self.account_id = env.get("BROKER_ACCOUNT_NUMBER")
        self.api_key = env.get("BROKER_API_KEY")
        self.credential_hash = hashlib.sha256(
            (self.api_key or "").encode("utf-8")
        ).hexdigest()
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }

    def _request(self, method, endpoint, data=None, params=None):
        url = f"{self.base_url}{endpoint}"
        return safe_request(method, url, headers=self.headers, json_data=data, params=params)

    def get_account_info(self):
        return self._request("GET", f"/v1/user/profile")

    def get_account_value(self):
        resp = self._request("GET", f"/v1/accounts/{self.account_id}/balances")
        return float(resp.get("balances", {}).get("total_equity", 0.0))

    def get_cash_balance(self):
        resp = self._request("GET", f"/v1/accounts/{self.account_id}/balances")
        return float(resp.get("balances", {}).get("cash_balance", 0.0))

    def get_positions(self):
        resp = self._request("GET", f"/v1/accounts/{self.account_id}/positions")
        positions = resp.get("positions", {}).get("position", [])
        # Always return a list of dicts, not a single dict
        if isinstance(positions, dict):
            positions = [positions]
        normalized_positions = []
        for pos in positions:
            normalized_positions.append({
                "symbol": pos.get("symbol"),
                "qty": float(pos.get("quantity") or 0),
                "market_value": float(pos.get("market_value") or 0),
                "unrealized_pl": float(pos.get("unrealized_pl", 0)),
                "purchase_price": float(pos.get("cost_basis", 0)),
                "currency": pos.get("currency", "USD"),
            })
        return normalized_positions

    def get_position(self, symbol):
        positions = self.get_positions()
        for pos in positions:
            if pos.get("symbol") == symbol:
                return pos
        return None

    def submit_order(self, order):
        payload = {
            "class": "equity",
            "symbol": order["symbol"],
            "side": order["side"],
            "quantity": order["qty"],
            "type": order.get("order_type", "market"),
            "duration": order.get("time_in_force", "day")
        }
        return self._request("POST", f"/v1/accounts/{self.account_id}/orders", data=payload)

    def place_order(self, symbol=None, side=None, amount=None, order=None):
        if order is not None:
            return self.submit_order(order)
        else:
            payload = {
                "class": "equity",
                "symbol": symbol,
                "side": side,
                "quantity": amount,
                "type": "market",
                "duration": "day"
            }
            return self._request("POST", f"/v1/accounts/{self.account_id}/orders", data=payload)

    def cancel_order(self, order_id):
        return self._request("DELETE", f"/v1/accounts/{self.account_id}/orders/{order_id}")

    def close_position(self, symbol):
        pos = self.get_position(symbol)
        if not pos:
            return {"message": f"No position to close for {symbol}"}
        side = "sell" if float(pos.get("qty", 0)) > 0 else "buy"
        order = {
            "symbol": symbol,
            "qty": abs(float(pos.get("qty", 0))),
            "side": side,
            "order_type": "market"
        }
        return self.submit_order(order)

    def is_market_open(self):
        status = self._request("GET", "/v1/markets/clock")
        return status.get("clock", {}).get("state", "").lower() == "open"

    def self_check(self):
        try:
            account = self.get_account_info()
            return account.get("profile", {}).get("status", "").lower() == "active"
        except Exception:
            return False

    def is_symbol_tradable(self, symbol):
        try:
            info = self._request("GET", f"/v1/markets/quotes", params={"symbols": symbol})
            return bool(info.get("quotes", {}).get("quote", {}).get("symbol", None))
        except Exception:
            return False

    def supports_fractional(self, symbol):
        return False

    def get_min_order_size(self, symbol):
        return 1.0

    def get_price(self, symbol):
        try:
            info = self._request("GET", f"/v1/markets/quotes", params={"symbols": symbol})
            quote = info.get("quotes", {}).get("quote", {})
            return float(quote.get("last", 0.0))
        except Exception:
            return 0.0

    def get_etf_holdings(self):
        positions = self.get_positions()
        etf_holdings = {}
        for pos in positions:
            sym = pos.get("symbol", "")
            mv = float(pos.get("market_value", 0.0))
            if sym and (sym.endswith("ETF") or sym.endswith("ET") or sym.endswith("SH") or sym.endswith("US")):
                etf_holdings[sym] = mv
        return etf_holdings

    def fetch_all_trades(self, start_date, end_date=None):
        params = {"start": start_date}
        if end_date:
            params["end"] = end_date
        resp = self._request("GET", f"/v1/accounts/{self.account_id}/history", params=params)
        trades = resp.get("history", {}).get("trade", [])
        return [normalize_trade(t, self.credential_hash) for t in trades]

    def fetch_cash_activity(self, start_date, end_date=None):
        params = {"start": start_date}
        if end_date:
            params["end"] = end_date
        resp = self._request("GET", f"/v1/accounts/{self.account_id}/history", params=params)
        activities = resp.get("history", {}).get("cash", [])
        return [normalize_trade(a, self.credential_hash) for a in activities]
