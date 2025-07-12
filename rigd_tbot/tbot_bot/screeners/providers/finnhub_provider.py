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
        """
        Accepts injected configuration and credentials dict.
        Required keys:
            - SCREENER_API_KEY or SCREENER_TOKEN
            - SCREENER_URL (default: https://finnhub.io/api/v1/)
            - SCREENER_USERNAME/SCREENER_PASSWORD (rare, optional)
            - API_TIMEOUT (int, default 30)
            - API_SLEEP (float, default 0.03)
            - LOG_LEVEL ('silent' or 'verbose')
        """
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
        self.sleep = float(self.config.get("API_SLEEP", 0.03))
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[FinnhubProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Fetches the full set of tradable US equities from Finnhub.
        Returns a list of dicts: symbol, exchange, name
        """
        url = f"{self.api_url.rstrip('/')}/stock/symbol?exchange=US&token={self.api_key}"
        try:
            resp = requests.get(url, timeout=self.timeout, auth=(self.username, self.password) if self.username and self.password else None)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self.log(f"Error fetching Finnhub symbols: {e}")
            return []
        syms = []
        for d in data:
            # Required: symbol, exchange, name
            if d.get("symbol") and d.get("type", "").upper() == "EQS":
                syms.append({
                    "symbol": d["symbol"].strip().upper(),
                    "exchange": d.get("exchange", "US"),
                    "name": d.get("description", "")
                })
        self.log(f"Fetched {len(syms)} Finnhub equity symbols.")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Fetches latest price/open/vwap and market cap for each symbol via Finnhub API.
        Returns list of dicts: {symbol, c, o, vwap, marketCap}
        """
        quotes = []
        for idx, symbol in enumerate(symbols):
            auth = (self.username, self.password) if self.username and self.password else None
            # Fetch quote (price)
            try:
                url_quote = f"{self.api_url.rstrip('/')}/quote?symbol={symbol}&token={self.api_key}"
                resp_q = requests.get(url_quote, timeout=self.timeout, auth=auth)
                if resp_q.status_code != 200:
                    self.log(f"Error fetching quote for {symbol}: HTTP {resp_q.status_code}")
                    continue
                data_q = resp_q.json()
                c = float(data_q.get("c", 0))
                o = float(data_q.get("o", 0))
                vwap = float(data_q.get("vwap", 0)) if "vwap" in data_q and data_q.get("vwap", 0) else (c if c else 0)
                # Fetch profile2 (market cap)
                url_profile = f"{self.api_url.rstrip('/')}/stock/profile2?symbol={symbol}&token={self.api_key}"
                resp_p = requests.get(url_profile, timeout=self.timeout, auth=auth)
                if resp_p.status_code != 200:
                    self.log(f"Error fetching profile2 for {symbol}: HTTP {resp_p.status_code}")
                    continue
                data_p = resp_p.json()
                market_cap = data_p.get("marketCapitalization", None)
                if c and market_cap:
                    quotes.append({
                        "symbol": symbol,
                        "c": c,
                        "o": o,
                        "vwap": vwap,
                        "marketCap": market_cap
                    })
                    if self.log_level == "verbose":
                        print(f"QUOTE[{idx}]: {symbol} | Close: {c} Open: {o} VWAP: {vwap} MarketCap: {market_cap}")
                else:
                    self.log(f"Skipping {symbol}: missing price or market cap")
            except Exception as e:
                self.log(f"Exception fetching quote/profile2 for {symbol}: {e}")
                continue
            if idx % 50 == 0 and idx > 0:
                self.log(f"Fetched quotes for {idx} symbols...")
            time.sleep(self.sleep)
        return quotes
