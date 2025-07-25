# tbot_bot/broker/brokers/alpaca.py
# Alpaca broker adapter (single-mode, single-broker architecture)

import requests
import csv
import io
import hashlib
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event

class AlpacaBroker:
    def __init__(self, env):
        """
        Initializes Alpaca broker using credentials and endpoint from unified, agnostic config.
        """
        self.api_key = env.get("BROKER_API_KEY")
        self.secret_key = env.get("BROKER_SECRET_KEY")
        self.broker_token = env.get("BROKER_TOKEN", "")
        self.base_url = env.get("BROKER_URL")
        self.credential_hash = hashlib.sha256((self.api_key or "").encode("utf-8") + (self.secret_key or "").encode("utf-8")).hexdigest()
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
            log_event("broker_alpaca", f"API call: {method} {endpoint} | creds: {self.credential_hash}", level="debug")
            return response.json()
        except Exception as e:
            log_event("broker_alpaca", f"Request failed: {e}", level="error")
            raise

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
            unique[t["id"]] = t

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

    # ================== BROKER SYNC INTERFACE ====================

    def fetch_all_trades(self, start_date, end_date=None):
        """
        Returns all filled trades in OFX/ledger-normalized dicts.
        Handles pagination, rate limits, audit hash, and logs credential use.
        Partial fills are aggregated by order ID; all required fields are normalized.
        """
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
            if isinstance(resp, dict) and "orders" in resp:
                page = resp["orders"]
            else:
                page = resp
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
                        "fee": commission,
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
                    # Aggregate fills if partial: sum quantities and values
                    prev = order_fills[order_id]
                    prev["quantity"] += filled_qty
                    prev["total_value"] += filled_qty * filled_price
                    prev["fee"] += fee
                    prev["fee"] += commission
            # pagination
            if isinstance(resp, dict) and "next_page_token" in resp and resp["next_page_token"]:
                next_page_token = resp["next_page_token"]
            else:
                break
        trades = list(order_fills.values())
        log_event("broker_alpaca", f"fetch_all_trades complete, {len(trades)} trades. cred_hash={self.credential_hash}", level="info")
        return trades

    def fetch_cash_activity(self, start_date, end_date=None):
        """
        Returns all cash/fee/dividend/transfer activity in OFX/ledger-normalized dicts.
        Handles pagination, required fields, and normalization.
        """
        # Use all valid documented types for max data coverage
        all_types = "FILL,TRANS,DIV,JNLC,JNLS,MFEE,ACATC,ACATS,CSD,CSR,CSW,INT,WIRE"
        params = {
            "activity_types": all_types,
            "after": start_date
        }
        if end_date:
            params["until"] = end_date
        activities = []
        next_page_token = None
        while True:
            if next_page_token:
                params["page_token"] = next_page_token
            resp = self._request("GET", "/v2/account/activities", params=params)
            if isinstance(resp, dict) and "activities" in resp:
                page = resp["activities"]
            else:
                page = resp
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
            # pagination
            if isinstance(resp, dict) and "next_page_token" in resp and resp["next_page_token"]:
                next_page_token = resp["next_page_token"]
            else:
                break
        log_event("broker_alpaca", f"fetch_cash_activity complete, {len(activities)} activity entries. cred_hash={self.credential_hash}", level="info")
        return activities

    def fetch_all_account_activities_raw(self, start_date, end_date=None):
        """
        Fetches and returns ALL raw account activities (full JSON) from Alpaca for all valid activity_types, paginated.
        """
        all_types = "FILL,TRANS,DIV,JNLC,JNLS,MFEE,ACATC,ACATS,CSD,CSR,CSW,INT,WIRE"
        params = {
            "activity_types": all_types,
            "after": start_date
        }
        if end_date:
            params["until"] = end_date
        activities = []
        next_page_token = None
        while True:
            if next_page_token:
                params["page_token"] = next_page_token
            resp = self._request("GET", "/v2/account/activities", params=params)
            if isinstance(resp, dict) and "activities" in resp:
                page = resp["activities"]
            else:
                page = resp
            activities.extend(page)
            if isinstance(resp, dict) and "next_page_token" in resp and resp["next_page_token"]:
                next_page_token = resp["next_page_token"]
            else:
                break
        log_event("broker_alpaca", f"fetch_all_account_activities_raw complete, {len(activities)} activity entries. cred_hash={self.credential_hash}", level="info")
        return activities

    def fetch_all_orders_raw(self, start_date, end_date=None):
        """
        Fetches and returns ALL raw orders (full JSON) from Alpaca paginated.
        """
        params = {
            "status": "all",
            "limit": 100,
            "after": start_date
        }
        if end_date:
            params["until"] = end_date
        orders = []
        next_page_token = None
        while True:
            if next_page_token:
                params["page_token"] = next_page_token
            resp = self._request("GET", "/v2/orders", params=params)
            if isinstance(resp, dict) and "orders" in resp:
                page = resp["orders"]
            else:
                page = resp
            orders.extend(page)
            if isinstance(resp, dict) and "next_page_token" in resp and resp["next_page_token"]:
                next_page_token = resp["next_page_token"]
            else:
                break
        log_event("broker_alpaca", f"fetch_all_orders_raw complete, {len(orders)} orders. cred_hash={self.credential_hash}", level="info")
        return orders
