# tbot_bot/screeners/providers/tradier_provider.py
# Tradier provider adapter: fetches quotes and symbols with injected config only.
# 100% stateless, no env or internal credential reads, ProviderBase-compliant.

import requests
import time
from typing import List, Dict, Optional

from tbot_bot.screeners.provider_base import ProviderBase

class TradierProvider(ProviderBase):
    """
    Tradier API provider adapter.
    Accepts config and credentials as a dict on init.
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Config must contain at least:
            - 'TRADIER_API_KEY' or 'BROKER_API_KEY' or 'SCREENER_API_KEY'
            - (optional) 'TRADIER_API_URL', 'LOG_LEVEL', 'API_TIMEOUT', 'API_SLEEP'
        """
        super().__init__(config)
        self.api_key = (
            self.config.get("TRADIER_API_KEY", "") or
            self.config.get("BROKER_API_KEY", "") or
            self.config.get("SCREENER_API_KEY", "")
        )
        self.base_url = self.config.get("TRADIER_API_URL", "https://api.tradier.com/v1/markets")
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()
        self.api_timeout = int(self.config.get("API_TIMEOUT", 30))
        self.api_sleep = float(self.config.get("API_SLEEP", 0.5))

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[TradierProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Tradier does not provide a universal symbol list via the API.
        This provider always returns an empty list; universe builder must inject symbols.
        """
        self.log("fetch_symbols() not implemented in TradierProvider (symbol list must be loaded elsewhere).")
        return []

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Fetches latest price, open, and vwap for each symbol using Tradier API (batch, 100 at a time).
        Returns list of dicts: [{"symbol":..., "c":..., "o":..., "vwap":...}, ...]
        """
        quotes = []
        HEADERS = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        BATCH_SIZE = 100
        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i:i+BATCH_SIZE]
            symbols_str = ",".join(batch)
            url = f"{self.base_url}/quotes"
            params = {"symbols": symbols_str}
            try:
                resp = requests.get(url, headers=HEADERS, params=params, timeout=self.api_timeout)
                if resp.status_code != 200:
                    self.log(f"Error fetching batch quotes: status {resp.status_code}")
                    continue
                data = resp.json().get("quotes", {}).get("quote", [])
                if isinstance(data, dict):
                    data = [data]
                for quote in data:
                    try:
                        symbol = quote.get("symbol")
                        last = float(quote.get("last", 0))
                        open_ = float(quote.get("open", 0))
                        high = float(quote.get("high", 0))
                        low = float(quote.get("low", 0))
                        vwap = (high + low + last) / 3 if high and low and last else last
                        quotes.append({
                            "symbol": symbol,
                            "c": last,
                            "o": open_,
                            "vwap": vwap
                        })
                    except Exception as e:
                        self.log(f"Exception parsing quote for {quote.get('symbol', 'unknown')}: {e}")
                        continue
            except Exception as e:
                self.log(f"Exception fetching batch quotes: {e}")
                continue
            time.sleep(self.api_sleep)
        return quotes
