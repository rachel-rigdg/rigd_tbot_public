# tbot_bot/broker/adapters/alpaca.py

import requests
import hashlib
from datetime import datetime, timezone
from tbot_bot.broker.utils.broker_request import safe_request
from tbot_bot.broker.utils.ledger_normalizer import normalize_trade


class AlpacaBroker:
    def __init__(self, env):
        self.api_key = env.get("BROKER_API_KEY")
        self.secret_key = env.get("BROKER_SECRET_KEY")
        self.broker_token = env.get("BROKER_TOKEN", "")
        self.base_url = (env.get("BROKER_URL") or "").rstrip("/")
        self.broker_code = (env.get("BROKER_CODE") or "ALPACA").upper()

        self.credential_hash = hashlib.sha256(
            (self.api_key or "").encode("utf-8") + (self.secret_key or "").encode("utf-8")
        ).hexdigest()

        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }
        if self.broker_token:
            self.headers["Authorization"] = f"Bearer {self.broker_token}"

    # ------------------------
    # Internal HTTP wrapper
    # ------------------------
    def _request(self, method, endpoint, data=None, params=None):
        url = f"{self.base_url}{endpoint}"
        return safe_request(method, url, headers=self.headers, json_data=data, params=params)

    # ------------------------
    # Core account/position endpoints (existing)
    # ------------------------
    def get_account_info(self):
        return self._request("GET", "/v2/account")

    def get_account_value(self):
        info = self.get_account_info()
        return float(info.get("equity", 0.0))

    def get_cash_balance(self):
        info = self.get_account_info()
        # Alpaca returns string numbers; normalize
        cash = info.get("cash") or info.get("cash_balance") or 0.0
        try:
            return float(cash)
        except Exception:
            return 0.0

    def get_positions(self):
        return self._request("GET", "/v2/positions")

    def get_position(self, symbol):
        try:
            return self._request("GET", f"/v2/positions/{symbol}")
        except Exception:
            return None

    # ------------------------
    # Orders
    # ------------------------
    def submit_order(self, order):
        """
        Generic order submit. Supports:
          - market/limit/stop/stop_limit (existing behavior)
          - trailing stop via either:
              order["type"] in {"trailing_stop","trail","trailing"} and
                order["trail_percent"] or order["trail_price"]
            OR
              order["trailing_stop_pct"] (fraction, e.g. 0.02) or order["trailing_stop_price"]
        """
        # Detect trailing-stop intent and route to trailing-stop submit
        otype = (order.get("order_type") or order.get("type") or "market").lower()
        trail_percent = order.get("trail_percent")
        trail_price = order.get("trail_price")
        # Back-compat keys from upstream order flow
        if trail_percent is None and "trailing_stop_pct" in order:
            try:
                # incoming fraction (e.g. 0.02) -> Alpaca percent units (2.0)
                trail_percent = float(order["trailing_stop_pct"]) * 100.0
            except Exception:
                trail_percent = None
        if trail_price is None and "trailing_stop_price" in order:
            try:
                trail_price = float(order["trailing_stop_price"])
            except Exception:
                trail_price = None

        if otype in {"trailing_stop", "trail", "trailing"} or trail_percent is not None or trail_price is not None:
            return self.submit_trailing_stop(
                symbol=order["symbol"],
                qty=order["qty"],
                side=order["side"],
                trail_percent=trail_percent,
                trail_price=trail_price,
                time_in_force=order.get("time_in_force", "day"),
                extended_hours=bool(order.get("extended_hours", False)),
                client_order_id=order.get("client_order_id")
            )

        payload = {
            "symbol": order["symbol"],
            "qty": order["qty"],
            "side": order["side"],
            "type": order.get("order_type", "market"),
            "time_in_force": order.get("time_in_force", "day"),
            "extended_hours": bool(order.get("extended_hours", False)),
        }
        if order.get("client_order_id"):
            payload["client_order_id"] = order["client_order_id"]

        # Optional price fields for limit/stop/stop_limit
        if "limit_price" in order:
            payload["limit_price"] = order["limit_price"]
        if "stop_price" in order:
            payload["stop_price"] = order["stop_price"]

        return self._request("POST", "/v2/orders", data=payload)

    def submit_trailing_stop(self, symbol, qty, side, trail_percent=None, trail_price=None,
                             time_in_force="day", extended_hours=False, client_order_id=None):
        """
        Submit a broker-side trailing stop order.

        Alpaca expects:
          type = "trailing_stop"
          trail_percent: percent in whole units (2.0 == 2%)
          OR
          trail_price: absolute price offset

        'side' should be:
          - "sell" to exit a LONG position
          - "buy"  to cover a SHORT position
        """
        payload = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": "trailing_stop",
            "time_in_force": time_in_force,
            "extended_hours": bool(extended_hours),
        }
        if client_order_id:
            payload["client_order_id"] = client_order_id

        # Prefer trail_percent if provided, else trail_price
        if trail_percent is not None:
            # Ensure numeric and positive
            try:
                tp = float(trail_percent)
                if tp <= 0:
                    raise ValueError("trail_percent must be > 0")
                payload["trail_percent"] = tp
            except Exception:
                # Fallback to trail_price if available
                if trail_price is None:
                    raise
        if "trail_percent" not in payload:
            if trail_price is None:
                raise ValueError("Must provide trail_percent or trail_price for trailing stop order")
            try:
                tr = float(trail_price)
                if tr <= 0:
                    raise ValueError("trail_price must be > 0")
                payload["trail_price"] = tr
            except Exception:
                raise

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
                "extended_hours": False,
            }
            return self._request("POST", "/v2/orders", data=payload)

    # ------------------------
    # Activities / trades (existing)
    # ------------------------
    def fetch_cash_activity(self, start_date, end_date=None):
        types = ["FILL", "TRANS", "DIV", "INT"]
        params = [("activity_types", t) for t in types]
        params.append(("after", start_date))
        if end_date:
            params.append(("until", end_date))
        try:
            acts = self._fetch_cash_activity_internal(params)
            # Ensure group_id for all normalized items
            normed = []
            for a in acts:
                trade = normalize_trade(a, self.credential_hash)
                if not trade.get("group_id"):
                    trade["group_id"] = trade.get("trade_id")
                normed.append(trade)
            return normed
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
            "after": start_date,
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
                            "credential_hash": self.credential_hash,
                        },
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
        # Normalize
        normed_trades = []
        for tf in order_fills.values():
            trade = normalize_trade(tf, self.credential_hash)
            if not trade.get("group_id"):
                trade["group_id"] = trade.get("trade_id")
            normed_trades.append(trade)
        return normed_trades

    def _fetch_cash_activity_internal(self, params):
        activities = []
        next_page_token = None
        while True:
            curr_params = list(params)
            if next_page_token:
                curr_params.append(("page_token", next_page_token))
            resp = self._request("GET", "/v2/account/activities", params=curr_params)
            page = resp if isinstance(resp, list) else resp.get("activities", [])
            for a in page:
                if not isinstance(a, dict):
                    continue
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
                        "credential_hash": self.credential_hash,
                    },
                }
                activities.append(activity)
            if isinstance(resp, dict) and "next_page_token" in resp and resp["next_page_token"]:
                next_page_token = resp["next_page_token"]
            else:
                break
        # Normalize
        normed_acts = []
        for act in activities:
            trade = normalize_trade(act, self.credential_hash)
            if not trade.get("group_id"):
                trade["group_id"] = trade.get("trade_id")
            normed_acts.append(trade)
        return normed_acts

    # ======================================================================
    # NEW: Trailing stop capability helpers
    # ======================================================================
    def supports_trailing_stop(self) -> bool:
        """
        Alpaca supports broker-side trailing stops via /v2/orders type=trailing_stop.
        """
        return True

    # --- Added for broker_api passthrough compatibility (plural form) ---
    def supports_trailing_stops(self) -> bool:
        """
        Plural alias used by broker_api.supports_trailing_stops().
        """
        return self.supports_trailing_stop()

    def place_trailing_stop(self, payload: dict):
        """
        Adapter-level entrypoint used by broker_api.place_trailing_stop(payload).

        Expected payload:
          {
            "symbol": "...", "qty": 1.23, "side": "sell",
            "trail_percent": 2.0,                  # preferred (2.0 == 2%)
            "trail_pct_fraction": 0.02,            # optional (mutually exclusive with trail_percent)
            # optional extras passed through when present:
            "time_in_force": "day", "extended_hours": False, "client_order_id": "..."
          }
        """
        symbol = payload.get("symbol")
        qty = payload.get("qty")
        side = payload.get("side")
        tip = payload.get("trail_percent", None)
        tpf = payload.get("trail_pct_fraction", None)
        tif = payload.get("time_in_force", "day")
        ext = bool(payload.get("extended_hours", False))
        coid = payload.get("client_order_id")

        # Normalize percent: prefer explicit percent; else convert fraction -> percent
        trail_percent = None
        if tip is not None:
            try:
                trail_percent = float(tip)
            except Exception:
                trail_percent = None
        if trail_percent is None and tpf is not None:
            try:
                trail_percent = float(tpf) * 100.0
            except Exception:
                trail_percent = None

        return self.submit_trailing_stop(
            symbol=symbol,
            qty=qty,
            side=side,
            trail_percent=trail_percent,
            trail_price=None,
            time_in_force=tif,
            extended_hours=ext,
            client_order_id=coid
        )

    # Lightweight reference price for qty estimation (used when FRACTIONAL=false)
    def get_last_price(self, symbol: str):
        # Reuse existing quote logic; Alpaca’s “latest quote” bid/ask midpoint isn’t guaranteed.
        # Using best bid/ask as a proxy is fine for sizing.
        return self.get_price(symbol)

    # ======================================================================
    # NEW: First-sync Opening Balance helpers (non-breaking additions)
    # ======================================================================
    def fetch_account(self):
        """
        Lightweight, normalized account snapshot for OB posting.

        Returns
        -------
        dict: {
          "account_id": str,
          "account_number": str|None,
          "cash": float,
          "equity": float,
          "currency": "USD" | str,
          "as_of_utc": ISO8601,
          "broker": "ALPACA",
          "credential_hash": "...",
          "raw": <original json>
        }
        """
        raw = self.get_account_info() or {}
        account_id = raw.get("id") or raw.get("account_id") or ""
        account_number = raw.get("account_number") or raw.get("number") or None
        currency = raw.get("currency") or "USD"

        def _f(x, default=0.0):
            try:
                return float(x)
            except Exception:
                return default

        snapshot = {
            "account_id": str(account_id or ""),
            "account_number": str(account_number) if account_number else None,
            "cash": _f(raw.get("cash") or raw.get("cash_balance"), 0.0),
            "equity": _f(raw.get("equity"), 0.0),
            "currency": str(currency),
            "as_of_utc": datetime.now(timezone.utc).isoformat(),
            "broker": self.broker_code,
            "credential_hash": self.credential_hash,
            "raw": raw,
        }
        return snapshot

    def fetch_positions(self):
        """
        Normalized open positions for OB posting.

        Returns
        -------
        list[dict]: each like {
          "symbol": "AAPL",
          "qty": 10.0,
          "avg_entry_price": 178.42 or None,
          "market_value": 1784.20 or 0.0,
          "cost_basis": 1784.20,
          "basis_type": "avg_entry_price" | "market_value_estimate",
          "memo": "... (only if estimated)",
          "account_id": "...",
          "broker": "ALPACA",
          "credential_hash": "...",
          "as_of_utc": ISO8601,
          "fitid_seed": "ALP_OB_<account_id>_<symbol>",
          "raw": <original json>
        }
        """
        # Fetch once so we can attach account_id to each row
        acct = self.fetch_account()
        account_id = acct.get("account_id") or ""

        raw_positions = self.get_positions() or []
        out = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for p in raw_positions:
            sym = p.get("symbol")
            # Alpaca uses strings for numerics; normalize carefully
            def _f(v):
                try:
                    return float(v)
                except Exception:
                    return 0.0

            qty = _f(p.get("qty") or p.get("quantity"))
            avg_entry_price = p.get("avg_entry_price")
            avg_entry_price = _f(avg_entry_price) if avg_entry_price not in (None, "") else None

            # Prefer true basis when available; otherwise fall back to MV and mark estimated
            market_value = _f(p.get("market_value"))
            if avg_entry_price is not None and avg_entry_price > 0 and qty != 0:
                cost_basis = avg_entry_price * qty
                basis_type = "avg_entry_price"
                memo = None
            else:
                cost_basis = market_value
                basis_type = "market_value_estimate"
                memo = "OB basis estimated from market_value; avg_entry_price unavailable"

            item = {
                "symbol": str(sym or "").upper(),
                "qty": qty,
                "avg_entry_price": avg_entry_price,
                "market_value": market_value,
                "cost_basis": cost_basis,
                "basis_type": basis_type,
                "memo": memo,
                "account_id": str(account_id),
                "broker": self.broker_code,
                "credential_hash": self.credential_hash,
                "as_of_utc": now_iso,
                "fitid_seed": f"{self.broker_code}_OB_{account_id}_{str(sym or '').upper()}",
                "raw": p,
            }
            out.append(item)

        return out

    # Convenience: combined OB snapshot (optional – doesn’t affect existing call sites)
    def fetch_opening_snapshot(self):
        """
        Returns a dict combining fetch_account() and fetch_positions().
        Useful if the sync step wants a single call for OB.
        """
        acct = self.fetch_account()
        pos = self.fetch_positions()
        return {"account": acct, "positions": pos, "as_of_utc": datetime.now(timezone.utc).isoformat()}
