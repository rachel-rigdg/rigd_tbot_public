# tbot_bot/screeners/providers/finnhub_provider.py
# Finnhub provider adapter: fetches symbols and quotes via injected API keys/config
# 100% provider-registry and credential-management compliant.

import requests
import time
from typing import List, Dict, Optional

from tbot_bot.screeners.provider_base import ProviderBase


class FinnhubProvider(ProviderBase):
    """
    Finnhub provider adapter for symbol and quote fetching.
    All config and credentials must be injected at init (no env reads).
    Implements ProviderBase.
    """

    def __init__(self, config: Optional[Dict] = None, creds: Optional[Dict] = None):
        merged = {}
        if config:
            merged.update(config)
        if creds:
            merged.update(creds)
        super().__init__(merged)
        self.api_key = (
            self.config.get("SCREENER_API_KEY", "") or
            self.config.get("SCREENER_TOKEN", "")
        )
        self.api_url = self.config.get("SCREENER_URL", "https://finnhub.io/api/v1/")
        self.username = self.config.get("SCREENER_USERNAME", "")
        self.password = self.config.get("SCREENER_PASSWORD", "")
        self.timeout = int(self.config.get("API_TIMEOUT", 30))
        self.sleep = float(self.config.get("UNIVERSE_SLEEP_TIME", 0.5))  # default 0.5s
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

        # --- Validate API key (fail fast; no requests without credentials) ---
        if not str(self.api_key).strip():
            raise ValueError("FINNHUB: Missing SCREENER_API_KEY/SCREENER_TOKEN; cannot initialize provider.")

    # ---------------- Internal helpers ----------------

    def _auth(self):
        return (self.username, self.password) if self.username and self.password else None

    def _raise_for_status(self, resp: requests.Response, ctx: str):
        if resp.status_code == 200:
            return
        # Explicit HTTP/JSON error surfacing for 4xx/5xx (incl. 401/403/429)
        body = None
        try:
            body = resp.text
        except Exception:
            body = "<unreadable body>"
        msg = f"FINNHUB {ctx}: HTTP {resp.status_code} — {body}"
        # Always log and raise
        self.log(msg)
        raise RuntimeError(msg)

    def _json_or_error(self, resp: requests.Response, ctx: str):
        try:
            data = resp.json()
        except Exception as e:
            msg = f"FINNHUB {ctx}: invalid JSON — {e}"
            self.log(msg)
            raise RuntimeError(msg)
        # Treat empty/None payloads as errors
        if data is None or (isinstance(data, list) and len(data) == 0) or (isinstance(data, dict) and len(data.keys()) == 0):
            msg = f"FINNHUB {ctx}: empty payload"
            self.log(msg)
            raise RuntimeError(msg)
        # Some Finnhub endpoints return {"error":"..."} on failure
        if isinstance(data, dict) and "error" in data and data.get("error"):
            msg = f"FINNHUB {ctx}: provider error — {data.get('error')}"
            self.log(msg)
            raise RuntimeError(msg)
        return data

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[FinnhubProvider] {msg}")

    # ---------------- Public API ----------------

    def fetch_symbols(self) -> List[Dict]:
        url = f"{self.api_url.rstrip('/')}/stock/symbol?exchange=US&token={self.api_key}"
        resp = requests.get(url, timeout=self.timeout, auth=self._auth())
        self._raise_for_status(resp, "fetch_symbols")
        data = self._json_or_error(resp, "fetch_symbols")

        syms = []
        # Expecting a list of dicts
        if not isinstance(data, list):
            raise RuntimeError(f"FINNHUB fetch_symbols: unexpected payload type {type(data)}")
        for d in data:
            symbol_val = (d.get("symbol") or "").strip().upper()
            exch = (d.get("mic") or "").strip().upper()  # MIC (e.g., XNAS, XNYS, ARCX)
            name = (d.get("description") or "").strip()
            if symbol_val and exch and name:
                syms.append({
                    "symbol": symbol_val,
                    "exchange": exch,          # leave MIC; normalized downstream
                    "companyName": name
                })

        # Empty post-filter list should still be considered an error to avoid silent fall-through
        if not syms:
            raise RuntimeError("FINNHUB fetch_symbols: no valid symbols returned after parsing payload.")
        self.log(f"Fetched {len(syms)} Finnhub equity symbols.")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        quotes = []
        for idx, symbol in enumerate(symbols):
            # --- Quote endpoint ---
            url_quote = f"{self.api_url.rstrip('/')}/quote?symbol={symbol}&token={self.api_key}"
            resp_q = requests.get(url_quote, timeout=self.timeout, auth=self._auth())
            self._raise_for_status(resp_q, f"fetch_quote[{symbol}]")
            data_q = self._json_or_error(resp_q, f"fetch_quote[{symbol}]")

            # Require a valid current price "c"
            c_val = data_q.get("c", None)
            if c_val is None or float(c_val) == 0.0:
                raise RuntimeError(f"FINNHUB fetch_quote[{symbol}]: missing/zero 'c' field in payload: {data_q}")

            c = float(c_val)
            o = float(data_q.get("o", 0) or 0)
            vwap = float(data_q.get("vwap", c) or c)

            # --- Company profile endpoint (market cap, etc.) ---
            url_profile = f"{self.api_url.rstrip('/')}/stock/profile2?symbol={symbol}&token={self.api_key}"
            resp_p = requests.get(url_profile, timeout=self.timeout, auth=self._auth())
            self._raise_for_status(resp_p, f"fetch_profile2[{symbol}]")
            data_p = self._json_or_error(resp_p, f"fetch_profile2[{symbol}]")

            market_cap = data_p.get("marketCapitalization", None)
            if market_cap in (None, 0, 0.0, "0", "0.0"):
                raise RuntimeError(f"FINNHUB fetch_profile2[{symbol}]: missing/zero 'marketCapitalization' in payload: {data_p}")

            quotes.append({
                "symbol": symbol,
                "c": c,
                "o": o,
                "vwap": vwap,
                "marketCap": market_cap
            })

            if idx % 50 == 0 and idx > 0:
                self.log(f"Fetched quotes for {idx} symbols...")
            time.sleep(self.sleep)

        return quotes
