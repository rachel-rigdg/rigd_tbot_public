# tbot_bot/screeners/providers/alpaca_provider.py
# Alpaca provider adapter: stateless, credential-injected, spec-compliant.
# Implements ProviderBase, fetches symbols and quotes via injected config/credentials only.

import requests
import time
from typing import List, Dict, Optional

from tbot_bot.screeners.provider_base import ProviderBase

class AlpacaProvider(ProviderBase):
    """
    Alpaca provider adapter for symbol and quote fetching.
    All config and credentials must be injected at init (no env reads).
    Implements ProviderBase.
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Accepts injected configuration and credentials dict.
        Required keys:
            - BROKER_API_KEY
            - BROKER_SECRET_KEY
            - BROKER_URL (default: https://data.alpaca.markets)
            - BROKER_TOKEN (optional)
            - BROKER_USERNAME / BROKER_PASSWORD (optional, rarely needed)
            - API_TIMEOUT (int, default 30)
            - API_SLEEP (float, default 0.2)
        """
        super().__init__(config)
        self.api_key = self.config.get("BROKER_API_KEY", "")
        self.secret_key = self.config.get("BROKER_SECRET_KEY", "")
        self.api_url = self.config.get("BROKER_URL", "https://data.alpaca.markets")
        self.bearer_token = self.config.get("BROKER_TOKEN", "")
        self.username = self.config.get("BROKER_USERNAME", "")
        self.password = self.config.get("BROKER_PASSWORD", "")
        self.timeout = int(self.config.get("API_TIMEOUT", 30))
        self.sleep = float(self.config.get("API_SLEEP", 0.2))
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }
        if self.bearer_token:
            self.headers["Authorization"] = f"Bearer {self.bearer_token}"

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[AlpacaProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Fetches the current list of tradable US equities from Alpaca.
        Returns a list of dicts with at least: symbol, exchange, name.
        """
        url = f"{self.api_url.rstrip('/')}/v2/assets"
        try:
            resp = requests.get(url, headers={k: v for k, v in self.headers.items() if v}, timeout=self.timeout)
            resp.raise_for_status()
            assets = resp.json()
        except Exception as e:
            self.log(f"Error fetching Alpaca symbols: {e}")
            return []
        syms = []
        for a in assets:
            if (a.get("status") == "active" and
                a.get("tradable", False) and
                a.get("exchange") in ("NASDAQ", "NYSE", "ARCA")):
                syms.append({
                    "symbol": a["symbol"].strip().upper(),
                    "exchange": a["exchange"],
                    "name": a.get("name", "")
                })
        self.log(f"Fetched {len(syms)} active Alpaca symbols.")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Fetches latest daily close/open/vwap for given symbols via Alpaca API.
        Returns list of dicts: {symbol, c, o, vwap}
        """
        quotes = []
        for idx, symbol in enumerate(symbols):
            url = f"{self.api_url.rstrip('/')}/v2/stocks/{symbol}/bars?timeframe=1Day&limit=1"
            auth = (self.username, self.password) if self.username and self.password else None
            try:
                resp = requests.get(url, headers={k: v for k, v in self.headers.items() if v}, timeout=self.timeout, auth=auth)
                if resp.status_code != 200:
                    self.log(f"Error fetching bars for {symbol}: HTTP {resp.status_code}")
                    continue
                bars = resp.json().get("bars", [])
                if not bars:
                    self.log(f"No bars found for {symbol}")
                    continue
                bar = bars[0]
                current = float(bar.get("c", 0))
                open_ = float(bar.get("o", 0))
                if all(k in bar for k in ("h", "l", "c")):
                    vwap = (bar["h"] + bar["l"] + bar["c"]) / 3
                else:
                    vwap = current
                quotes.append({
                    "symbol": symbol,
                    "c": current,
                    "o": open_,
                    "vwap": vwap
                })
            except Exception as e:
                self.log(f"Exception fetching quote for {symbol}: {e}")
                continue
            if idx % 50 == 0 and idx > 0:
                self.log(f"Fetched quotes for {idx} symbols...")
            time.sleep(self.sleep)
        return quotes
