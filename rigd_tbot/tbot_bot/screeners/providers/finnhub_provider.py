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
        self.sleep = 2.0
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[FinnhubProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
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
            symbol_val = d.get("symbol")
            exch = d.get("mic", "")  # Use 'mic' for exchange
            name = d.get("description", "")
            # Only filter out symbols if they are clearly broken/missing
            if symbol_val and exch and name:
                syms.append({
                    "symbol": symbol_val.strip().upper(),
                    "exchange": exch.strip().upper(),
                    "companyName": name
                })
        self.log(f"Fetched {len(syms)} Finnhub equity symbols.")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        quotes = []
        for idx, symbol in enumerate(symbols):
            auth = (self.username, self.password) if self.username and self.password else None
            try:
                # Retry mechanism for quote
                data_q = None
                for attempt in range(3):
                    url_quote = f"{self.api_url.rstrip('/')}/quote?symbol={symbol}&token={self.api_key}"
                    resp_q = requests.get(url_quote, timeout=self.timeout, auth=auth)
                    if resp_q.status_code == 200:
                        data_q = resp_q.json()
                        break
                    elif resp_q.status_code in (429, 503):
                        self.log(f"Rate limited or service unavailable fetching quote for {symbol}, attempt {attempt + 1}/3")
                        time.sleep(self.sleep * (attempt + 1))
                    else:
                        self.log(f"Error fetching quote for {symbol}: HTTP {resp_q.status_code}")
                        break
                if not data_q or data_q.get("c") is None or data_q.get("c") == 0:
                    self.log(f"Skipping {symbol}: no valid quote data (not found or missing fields)")
                    continue

                c = float(data_q.get("c", 0))
                o = float(data_q.get("o", 0))
                vwap = float(data_q.get("vwap", 0)) if "vwap" in data_q and data_q.get("vwap", 0) else (c if c else 0)

                # Retry mechanism for profile2
                data_p = None
                for attempt in range(3):
                    url_profile = f"{self.api_url.rstrip('/')}/stock/profile2?symbol={symbol}&token={self.api_key}"
                    resp_p = requests.get(url_profile, timeout=self.timeout, auth=auth)
                    if resp_p.status_code == 200:
                        data_p = resp_p.json()
                        break
                    elif resp_p.status_code in (429, 503):
                        self.log(f"Rate limited or service unavailable fetching profile2 for {symbol}, attempt {attempt + 1}/3")
                        time.sleep(self.sleep * (attempt + 1))
                    else:
                        self.log(f"Error fetching profile2 for {symbol}: HTTP {resp_p.status_code}")
                        break
                if not data_p or data_p.get("marketCapitalization") is None or data_p.get("marketCapitalization") == 0:
                    self.log(f"Skipping {symbol}: no valid profile2 data (not found or missing fields)")
                    continue

                market_cap = data_p.get("marketCapitalization", None)
                quotes.append({
                    "symbol": symbol,
                    "c": c,
                    "o": o,
                    "vwap": vwap,
                    "marketCap": market_cap
                })
            except Exception as e:
                self.log(f"Exception fetching quote/profile2 for {symbol}: {e}")
                continue
            if idx % 50 == 0 and idx > 0:
                self.log(f"Fetched quotes for {idx} symbols...")
            time.sleep(self.sleep)
        return quotes
