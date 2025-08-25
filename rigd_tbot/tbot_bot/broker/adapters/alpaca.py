# tbot_bot/broker/adapters/alpaca.py

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from tbot_bot.broker.utils.broker_request import safe_request


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _coerce_utc_z(s: Optional[str]) -> Optional[str]:
    # safe_request already coerces many ISO fields to UTC Z; this is a light safeguard.
    if not s or not isinstance(s, str):
        return None
    if s.endswith("Z"):
        return s
    # naive fallback — rely on safe_request primary coercion; keep original if unknown
    return s


class AlpacaBroker:
    def __init__(self, env: Dict[str, Any]):
        self.api_key = env.get("BROKER_API_KEY")
        self.secret_key = env.get("BROKER_SECRET_KEY")
        self.broker_token = env.get("BROKER_TOKEN", "")
        self.base_url = (env.get("BROKER_URL") or "").rstrip("/")
        cred_concat = f"{self.api_key or ''}:{self.secret_key or ''}"
        self.credential_hash = hashlib.sha256(cred_concat.encode("utf-8")).hexdigest()
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }
        if self.broker_token:
            self.headers["Authorization"] = f"Bearer {self.broker_token}"

    # ---------------------------
    # Low-level request wrapper
    # ---------------------------

    def _request(self, method: str, endpoint: str, data: Dict[str, Any] = None, params: Dict[str, Any] = None):
        url = f"{self.base_url}{endpoint}"
        return safe_request(method, url, headers=self.headers, json_data=data, params=params)

    # ---------------------------
    # Account / misc helpers
    # ---------------------------

    def get_account_info(self) -> Dict[str, Any]:
        return self._request("GET", "/v2/account")

    def get_account_value(self) -> float:
        info = self.get_account_info()
        return _to_float(info.get("equity"))

    def get_cash_balance(self) -> float:
        info = self.get_account_info()
        return _to_float(info.get("cash"))

    def is_market_open(self) -> bool:
        clock = self._request("GET", "/v2/clock")
        return bool(clock.get("is_open", False))

    def is_symbol_tradable(self, symbol: str) -> bool:
        try:
            resp = self._request("GET", f"/v2/assets/{symbol}")
            return bool(resp.get("tradable", False))
        except Exception:
            return False

    def supports_fractional(self, symbol: str) -> bool:
        try:
            resp = self._request("GET", f"/v2/assets/{symbol}")
            return bool(resp.get("fractionable", False))
        except Exception:
            return False

    def get_min_order_size(self, symbol: str) -> float:
        try:
            resp = self._request("GET", f"/v2/assets/{symbol}")
            v = resp.get("min_order_size")
            return _to_float(v) if v is not None else 1.0
        except Exception:
            return 1.0

    def get_price(self, symbol: str) -> float:
        try:
            resp = self._request("GET", f"/v2/stocks/{symbol}/quotes/latest")
            price = resp.get("quote", {}).get("bp") or resp.get("quote", {}).get("ap")
            return _to_float(price)
        except Exception:
            return 0.0

    # ---------------------------
    # Orders
    # ---------------------------

    def submit_order(self, order: Dict[str, Any]):
        payload = {
            "symbol": order["symbol"],
            "qty": order["qty"],
            "side": order["side"],
            "type": order.get("order_type", "market"),
            "time_in_force": order.get("time_in_force", "day"),
            "extended_hours": bool(order.get("extended_hours", False)),
        }
        return self._request("POST", "/v2/orders", data=payload)

    def place_order(self, symbol: Optional[str] = None, side: Optional[str] = None, amount: Optional[float] = None, order: Dict[str, Any] = None):
        if order is not None:
            return self.submit_order(order)
        payload = {
            "symbol": symbol,
            "qty": amount,
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "extended_hours": False,
        }
        return self._request("POST", "/v2/orders", data=payload)

    def cancel_order(self, order_id: str):
        return self._request("DELETE", f"/v2/orders/{order_id}")

    def close_position(self, symbol: str):
        return self._request("DELETE", f"/v2/positions/{symbol}")

    # ---------------------------
    # RAW retrieval (for normalizers)
    # ---------------------------

    def _orders_page(self, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        resp = self._request("GET", "/v2/orders", params=params)
        # Alpaca may return a list or an object with 'orders' and 'next_page_token'
        if isinstance(resp, list):
            return resp, None
        if isinstance(resp, dict):
            return resp.get("orders", []) or [], resp.get("next_page_token")
        return [], None

    def get_trades(self, start_utc: str, end_utc: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return RAW order/fill-like records with canonical fields and stable FITID seeds.
        Pagination with page_token; retries handled by safe_request.
        """
        params: Dict[str, Any] = {
            "status": "all",  # include to allow consumer-side filtering
            "limit": 100,
            "after": start_utc,
        }
        if end_utc:
            params["until"] = end_utc

        next_token: Optional[str] = None
        raw: List[Dict[str, Any]] = []
        seen_ids = set()

        while True:
            if next_token:
                params["page_token"] = next_token
            page, next_token = self._orders_page(params)

            for t in page:
                if not isinstance(t, dict):
                    continue
                oid = t.get("id")
                if oid in seen_ids:
                    continue
                seen_ids.add(oid)

                filled_qty = _to_float(t.get("filled_qty") or t.get("qty"))
                filled_price = _to_float(t.get("filled_avg_price"))
                dt = _coerce_utc_z(t.get("filled_at") or t.get("submitted_at"))

                rec: Dict[str, Any] = {
                    "trade_id": oid,
                    "order_id": oid,
                    "execution_id": None,  # Alpaca orders API does not provide per-fill IDs
                    "symbol": t.get("symbol"),
                    "side": t.get("side"),
                    "action": t.get("side"),
                    "quantity": filled_qty,
                    "price": filled_price,
                    "fee": _to_float(t.get("filled_fee") or 0),
                    "commission": _to_float(t.get("commission") or 0),
                    "datetime_utc": dt,
                    "status": t.get("status"),
                    "total_value": filled_qty * filled_price,
                    "json_metadata": {
                        "source": "alpaca",
                        "endpoint": "/v2/orders",
                        "raw_broker": t,
                        "api_hash": hashlib.sha256(str(t).encode("utf-8")).hexdigest(),
                        "credential_hash": self.credential_hash,
                    },
                }
                # Stable FITID seed
                base = rec["trade_id"] or rec["order_id"] or rec["json_metadata"]["api_hash"]
                rec["stable_id"] = _sha1(f"ALPACA:{self.credential_hash}:{base}")
                raw.append(rec)

            if not next_token:
                break

        return raw

    def _activities_page(self, params_items: List[Tuple[str, str]]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        resp = self._request("GET", "/v2/account/activities", params=params_items)
        if isinstance(resp, list):
            return resp, None
        if isinstance(resp, dict):
            return resp.get("activities", []) or [], resp.get("next_page_token")
        return [], None

    def get_activities(self, start_utc: str, end_utc: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return RAW cash/activity records with canonical fields and stable FITID seeds.
        """
        types = ["FILL", "TRANS", "DIV", "INT"]
        base_items: List[Tuple[str, str]] = [("activity_types", t) for t in types]
        base_items.append(("after", start_utc))
        if end_utc:
            base_items.append(("until", end_utc))

        next_token: Optional[str] = None
        raw: List[Dict[str, Any]] = []

        while True:
            items = list(base_items)
            if next_token:
                items.append(("page_token", next_token))
            page, next_token = self._activities_page(items)

            for a in page:
                if not isinstance(a, dict):
                    continue
                aid = a.get("id") or a.get("activity_id")
                qty = _to_float(a.get("qty"))
                price = _to_float(a.get("price"))
                dt = _coerce_utc_z(a.get("transaction_time") or a.get("date"))

                rec: Dict[str, Any] = {
                    "activity_id": aid,
                    "symbol": a.get("symbol"),
                    "action": a.get("activity_type"),
                    "quantity": qty,
                    "price": price,
                    "fee": _to_float(a.get("fee")),
                    "commission": _to_float(a.get("commission")),
                    "datetime_utc": dt,
                    "status": a.get("status"),
                    "total_value": qty * price,
                    "json_metadata": {
                        "source": "alpaca",
                        "endpoint": "/v2/account/activities",
                        "raw_broker": a,
                        "api_hash": hashlib.sha256(str(a).encode("utf-8")).hexdigest(),
                        "credential_hash": self.credential_hash,
                    },
                }
                base = rec["activity_id"] or rec["json_metadata"]["api_hash"]
                rec["stable_id"] = _sha1(f"ALPACA:{self.credential_hash}:{base}")
                raw.append(rec)

            if not next_token:
                break

        return raw

    def get_positions(self, as_of_utc: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return RAW open positions snapshot with canonical fields and stable seeds.
        """
        resp = self._request("GET", "/v2/positions")
        page = resp if isinstance(resp, list) else []
        raw: List[Dict[str, Any]] = []

        for p in page:
            if not isinstance(p, dict):
                continue
            symbol = p.get("symbol")
            qty = _to_float(p.get("qty") or p.get("quantity"))
            avg = _to_float(p.get("avg_entry_price"))
            mv = _to_float(p.get("market_value"))
            dt = _coerce_utc_z(p.get("updated_at") or p.get("timestamp"))

            rec: Dict[str, Any] = {
                "position_id": p.get("asset_id") or symbol,
                "symbol": symbol,
                "qty": qty,
                "avg_entry_price": avg,
                "market_value": mv,
                "cost_basis": qty * avg if avg and qty else _to_float(p.get("cost_basis")),
                "datetime_utc": dt,
                "json_metadata": {
                    "source": "alpaca",
                    "endpoint": "/v2/positions",
                    "raw_broker": p,
                    "api_hash": hashlib.sha256(str(p).encode("utf-8")).hexdigest(),
                    "credential_hash": self.credential_hash,
                },
            }
            base = rec["position_id"] or symbol or rec["json_metadata"]["api_hash"]
            rec["stable_id"] = _sha1(f"ALPACA:{self.credential_hash}:{base}")
            raw.append(rec)

        return raw

    # ---------------------------
    # Back-compat shims
    # ---------------------------

    def fetch_all_trades(self, start_date: str, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.get_trades(start_date, end_date)

    def fetch_cash_activity(self, start_date: str, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.get_activities(start_date, end_date)

    # ---------------------------
    # Convenience
    # ---------------------------

    def get_etf_holdings(self) -> Dict[str, float]:
        positions = self.get_positions()
        etf_holdings: Dict[str, float] = {}
        for pos in positions:
            sym = pos.get("symbol")
            mv = _to_float(pos.get("market_value"))
            if not sym:
                continue
            if any(sym.endswith(suf) for suf in ("ETF", "ET", "SH", "US")):
                etf_holdings[sym] = mv
        return etf_holdings
