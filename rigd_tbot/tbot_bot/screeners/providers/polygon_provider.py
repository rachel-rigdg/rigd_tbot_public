# tbot_bot/screeners/providers/polygon_provider.py
# Polygon provider adapter: fetches symbols and quotes using injected API keys/config.
# 100% stateless, all configuration and credentials must be injected by caller.

import requests
from typing import List, Dict, Optional

from tbot_bot.screeners.provider_base import ProviderBase

class PolygonProvider(ProviderBase):
    """
    Polygon adapter for symbol/metadata and quote loading.
    Requires injected config/credentials dict (never reads env).
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Expects config dict with at least:
            - 'POLYGON_API_KEY' or 'SCREENER_API_KEY' or 'SCREENER_TOKEN'
            - optionally 'exchanges' (list, e.g. ['NASDAQ', 'NYSE'])
        """
        super().__init__(config)
        self.api_key = (
            self.config.get("POLYGON_API_KEY", "") or
            self.config.get("SCREENER_API_KEY", "") or
            self.config.get("SCREENER_TOKEN", "")
        )
        self.exchanges = set(e.upper() for e in (self.config.get("exchanges") or ["NASDAQ", "NYSE"]))
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[PolygonProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Loads symbols and metadata from Polygon.io API.
        Only symbols from the target exchanges are included.
        Returns list of dicts: {symbol, exchange, companyName}
        """
        url = f"https://api.polygon.io/v3/reference/tickers"
        params = {
            "market": "stocks",
            "active": "true",
            "apiKey": self.api_key,
            "limit": 1000,
            "order": "asc"
        }
        syms = []
        next_url = url
        while next_url:
            resp = requests.get(next_url, params=params if next_url == url else None)
            if resp.status_code != 200:
                self.log(f"API error: {resp.status_code} {resp.text}")
                break
            data = resp.json()
            for t in data.get("results", []):
                exch_code = t.get("primary_exchange")
                symbol = t.get("ticker", "").upper()
                name = t.get("name", "")
                if exch_code == "XNAS":
                    exch = "NASDAQ"
                elif exch_code == "XNYS":
                    exch = "NYSE"
                else:
                    exch = exch_code or "US"
                if exch in self.exchanges:
                    syms.append({
                        "symbol": symbol,
                        "exchange": exch,
                        "companyName": name
                    })
            next_url = data.get("next_url")
            params = None
        self.log(f"Fetched {len(syms)} Polygon symbols.")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Fetches latest daily close/open/vwap for given symbols via Polygon API.
        Returns list of dicts: {symbol, c, o, vwap}
        """
        quotes = []
        base_url = "https://api.polygon.io/v2/aggs/ticker"
        for idx, symbol in enumerate(symbols):
            url = f"{base_url}/{symbol}/prev"
            params = {"adjusted": "true", "apiKey": self.api_key}
            try:
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code != 200:
                    self.log(f"Polygon error for {symbol}: HTTP {resp.status_code} {resp.text}")
                    continue
                results = resp.json().get("results", [])
                if not results:
                    self.log(f"No Polygon agg data for {symbol}")
                    continue
                bar = results[0]
                close = float(bar.get("c", 0))
                open_ = float(bar.get("o", 0))
                high = float(bar.get("h", 0))
                low = float(bar.get("l", 0))
                vwap = (high + low + close) / 3 if all([high, low, close]) else close
                quotes.append({
                    "symbol": symbol,
                    "c": close,
                    "o": open_,
                    "vwap": vwap
                })
            except Exception as e:
                self.log(f"Exception fetching Polygon quote for {symbol}: {e}")
                continue
            if idx % 50 == 0 and idx > 0:
                self.log(f"Fetched Polygon quotes for {idx} symbols...")
        return quotes
