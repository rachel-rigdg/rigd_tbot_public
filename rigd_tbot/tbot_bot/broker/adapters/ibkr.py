# tbot_bot/broker/adapters/ibkr.py

import hashlib
from tbot_bot.broker.core.broker_interface import BrokerInterface
from tbot_bot.broker.utils.broker_request import safe_request
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade

class IBKRBroker(BrokerInterface):
    def __init__(self, env):
        super().__init__(env)
        self.base_url = env.get("BROKER_URL")
        self.account_id = env.get("BROKER_ACCOUNT_NUMBER")
        self.api_key = env.get("BROKER_API_KEY")
        self.api_secret = env.get("BROKER_SECRET_KEY")
        self.credential_hash = hashlib.sha256(
            (self.api_key or "").encode("utf-8") + (self.api_secret or "").encode("utf-8")
        ).hexdigest()
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

    def _request(self, method, endpoint, data=None, params=None):
        url = f"{self.base_url}{endpoint}"
        return safe_request(method, url, headers=self.headers, json_data=data, params=params)

    def get_account_info(self):
        return self._request("GET", f"/v1/accounts/{self.account_id}")

    def get_positions(self):
        resp = self._request("GET", f"/v1/accounts/{self.account_id}/positions")
        positions = resp.get("positions", resp)
        normalized_positions = []
        for pos in positions:
            normalized_positions.append({
                "symbol": pos.get("symbol"),
                "qty": float(pos.get("quantity") or 0),
                "market_value": float(pos.get("marketValue") or 0),
                "unrealized_pl": float(pos.get("unrealizedPnL") or 0),
                "purchase_price": float(pos.get("averageCost") or 0),
                "currency": pos.get("currency"),
            })
        return normalized_positions

    def get_position(self, symbol):
        try:
            positions = self.get_positions()
            for pos in positions:
                if pos.get("symbol") == symbol:
                    return pos
            return None
        except Exception:
            return None

    def submit_order(self, order):
        payload = {
            "symbol": order["symbol"],
            "qty": order["qty"],
            "side": order["side"],
            "type": order.get("order_type", "market"),
            "tif": order.get("time_in_force", "DAY")
        }
        return self._request("POST", f"/v1/accounts/{self.account_id}/orders", data=payload)

    def place_order(self, symbol=None, side=None, amount=None, order=None):
        if order is not None:
            return self.submit_order(order)
        else:
            payload = {
                "symbol": symbol,
                "qty": amount,
                "side": side,
                "type": "market",
                "tif": "DAY"
            }
            return self._request("POST", f"/v1/accounts/{self.account_id}/orders", data=payload)

    def cancel_order(self, order_id):
        return self._request("DELETE", f"/v1/accounts/{self.account_id}/orders/{order_id}")

    def close_position(self, symbol):
        return self._request("DELETE", f"/v1/accounts/{self.account_id}/positions/{symbol}")

    def is_symbol_tradable(self, symbol):
        try:
            resp = self._request("GET", f"/v1/marketdata/{symbol}/tradable")
            return resp.get("tradable", False)
        except Exception:
            return False

    def supports_fractional(self, symbol):
        try:
            resp = self._request("GET", f"/v1/marketdata/{symbol}/fractional")
            return resp.get("fractional", False)
        except Exception:
            return False

    def get_min_order_size(self, symbol):
        try:
            resp = self._request("GET", f"/v1/marketdata/{symbol}/min_order_size")
            return float(resp.get("min_order_size", 1.0))
        except Exception:
            return 1.0

    def get_price(self, symbol):
        try:
            resp = self._request("GET", f"/v1/marketdata/{symbol}/quote")
            price = resp.get("last", {}).get("price", 0.0)
            return float(price)
        except Exception:
            return 0.0

    def fetch_all_trades(self, start_date, end_date=None):
        params = {"from": start_date}
        if end_date:
            params["to"] = end_date
        resp = self._request("GET", f"/v1/accounts/{self.account_id}/trades", params=params)
        trades = resp.get("trades", resp)
        return [normalize_trade(t, self.credential_hash) for t in trades]

    def fetch_cash_activity(self, start_date, end_date=None):
        params = {"from": start_date}
        if end_date:
            params["to"] = end_date
        resp = self._request("GET", f"/v1/accounts/{self.account_id}/transactions", params=params)
        acts = resp.get("transactions", resp)
        return [normalize_trade(a, self.credential_hash) for a in acts]

    def get_etf_holdings(self):
        try:
            positions = self.get_positions()
            etf_holdings = {}
            for pos in positions:
                sym = pos.get("symbol")
                mv = float(pos.get("market_value", 0.0))
                if sym and any(sym.endswith(suf) for suf in ("ETF", "ET", "SH", "US")):
                    etf_holdings[sym] = mv
            return etf_holdings
        except Exception:
            return {}

    def self_check(self):
        try:
            account = self.get_account_info()
            return account.get("accountStatus", "").upper() == "OPEN"
        except Exception:
            return False
