# tbot_bot/broker/adapters/alpaca.py

import requests
import hashlib
from tbot_bot.broker.utils.broker_request import safe_request
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade

class AlpacaBroker:
    def __init__(self, env):
        self.api_key = env.get("BROKER_API_KEY")
        self.secret_key = env.get("BROKER_SECRET_KEY")
        self.broker_token = env.get("BROKER_TOKEN", "")
        self.base_url = env.get("BROKER_URL")
        self.credential_hash = hashlib.sha256(
            (self.api_key or "").encode("utf-8") + (self.secret_key or "").encode("utf-8")
        ).hexdigest()
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key
        }
        if self.broker_token:
            self.headers["Authorization"] = f"Bearer {self.broker_token}"

    def _request(self, method, endpoint, data=None, params=None):
        url = f"{self.base_url}{endpoint}"
        return safe_request(method, url, headers=self.headers, json_data=data, params=params)

    def get_account_info(self):
        return self._request("GET", "/v2/account")

    def get_account_value(self):
        info = self.get_account_info()
        return float(info.get("equity", 0.0))

    def get_cash_balance(self):
        info = self.get_account_info()
        return float(info.get("cash", 0.0))

    def get_positions(self):
        return self._request("GET", "/v2/positions")

    def get_position(self, symbol):
        try:
            return self._request("GET", f"/v2/positions/{symbol}")
        except Exception:
            return None

    def submit_order(self, order):
        payload = {
            "symbol": order["symbol"],
            "qty": order["qty"],
            "side": order["side"],
            "type": order.get("order_type", "market"),
            "time_in_force": order.get("time_in_force", "day"),
            "extended_hours": False
        }
        return self._request("POST", "/v2/orders", data=payload)

    def place_order(self, symbol=None, side=None, amount=None, order=None):
        if order is not None:
            return self.submit_order(order)
        else:
            payload = {
                "symbol": symbol,
                "qty": amount,
                "side": side,
                "type": "market",
                "time_in_force": "day",
                "extended_hours": False
            }
            return self._request("POST", "/v2/orders", data=payload)

    def fetch_cash_activity(self, start_date, end_date=None):
        all_types_safe = "FILL,TRANS,DIV,MFEE,INT,WIRE"
        params = {"activity_types": all_types_safe, "after": start_date}
        if end_date:
            params["until"] = end_date
        try:
            return self._fetch_cash_activity_internal(params)
        except Exception:
            return []

    def cancel_order(self, order_id):
        return self._request("DELETE", f"/v2/orders/{order_id}")

    def close_position(self, symbol):
        return self._request("DELETE", f"/v2/positions/{symbol}")

    def is_market_open(self):
        clock = self._request("GET", "/v2/clock")
        return clock.get("is_open", False)

    def is_symbol_tradable(self, symbol):
        try:
            resp = self._request("GET", f"/v2/assets/{symbol}")
            return resp.get("tradable", False)
        except Exception:
            return False

    def supports_fractional(self, symbol):
        try:
            resp = self._request("GET", f"/v2/assets/{symbol}")
            return resp.get("fractionable", False)
        except Exception:
            return False

    def get_min_order_size(self, symbol):
        try:
            resp = self._request("GET", f"/v2/assets/{symbol}")
            min_size = resp.get("min_order_size", None)
            return float(min_size) if min_size is not None else 1.0
        except Exception:
            return 1.0

    def get_price(self, symbol):
        try:
            resp = self._request("GET", f"/v2/stocks/{symbol}/quotes/latest")
            price = resp.get("quote", {}).get("bp")
            if price is None:
                price = resp.get("quote", {}).get("ap")
            return float(price) if price else 0.0
        except Exception:
            return 0.0

    def get_etf_holdings(self):
        positions = self.get_positions()
        etf_holdings = {}
        for pos in positions:
            sym = pos.get("symbol")
            mv = float(pos.get("market_value", 0.0))
            if sym and any(sym.endswith(suf) for suf in ("ETF", "ET", "SH", "US")):
                etf_holdings[sym] = mv
        return etf_holdings

    def fetch_all_trades(self, start_date, end_date=None):
        params = {
            "status": "filled",
            "limit": 100,
            "after": start_date
        }
        if end_date:
            params["until"] = end_date
        trades = []
        next_page_token = None
        order_fills = {}
        while True:
            if next_page_token:
                params["page_token"] = next_page_token
            resp = self._request("GET", "/v2/orders", params=params)
            page = resp["orders"] if isinstance(resp, dict) and "orders" in resp else resp
            for t in page:
                order_id = t.get("id")
                filled_qty = float(t.get("filled_qty") or t.get("qty") or 0)
                filled_price = float(t.get("filled_avg_price") or 0)
                fee = float(t.get("filled_fee") or 0) if "filled_fee" in t else 0
                commission = float(t.get("commission", 0)) if "commission" in t else 0
                t_hash = hashlib.sha256(str(t).encode("utf-8")).hexdigest()
                if order_id not in order_fills:
                    order_fills[order_id] = {
                        "trade_id": order_id,
                        "symbol": t.get("symbol"),
                        "action": t.get("side"),
                        "quantity": filled_qty,
                        "price": filled_price,
                        "fee": fee,
                        "commission": commission,
                        "datetime_utc": t.get("filled_at"),
                        "status": t.get("status"),
                        "total_value": filled_qty * filled_price,
                        "json_metadata": {
                            "raw_broker": t,
                            "api_hash": t_hash,
                            "credential_hash": self.credential_hash
                        }
                    }
                else:
                    prev = order_fills[order_id]
                    prev["quantity"] += filled_qty
                    prev["total_value"] += filled_qty * filled_price
                    prev["fee"] += fee
                    prev["commission"] += commission
            if isinstance(resp, dict) and "next_page_token" in resp and resp["next_page_token"]:
                next_page_token = resp["next_page_token"]
            else:
                break
        return list(order_fills.values())

    def _fetch_cash_activity_internal(self, params):
        activities = []
        next_page_token = None
        while True:
            if next_page_token:
                params["page_token"] = next_page_token
            resp = self._request("GET", "/v2/account/activities", params=params)
            page = resp["activities"] if isinstance(resp, dict) and "activities" in resp else resp
            for a in page:
                a_hash = hashlib.sha256(str(a).encode("utf-8")).hexdigest()
                activity = {
                    "trade_id": a.get("id") or a.get("activity_id"),
                    "symbol": a.get("symbol"),
                    "action": a.get("activity_type"),
                    "quantity": float(a.get("qty") or 0),
                    "price": float(a.get("price") or 0),
                    "fee": float(a.get("fee") or 0),
                    "commission": float(a.get("commission", 0)) if "commission" in a else 0,
                    "datetime_utc": a.get("transaction_time"),
                    "status": a.get("status"),
                    "total_value": float(a.get("qty", 0)) * float(a.get("price", 0)),
                    "json_metadata": {
                        "raw_broker": a,
                        "api_hash": a_hash,
                        "credential_hash": self.credential_hash
                    }
                }
                activities.append(activity)
            if isinstance(resp, dict) and "next_page_token" in resp and resp["next_page_token"]:
                next_page_token = resp["next_page_token"]
            else:
                break
        return activities
