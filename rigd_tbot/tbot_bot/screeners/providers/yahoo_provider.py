# tbot_bot/screeners/providers/yahoo_provider.py
# Yahoo provider adapter: fetches US equity symbols/prices via yfinance, no CSV or user list required.

from typing import List, Dict, Optional
import yfinance as yf
from tbot_bot.screeners.provider_base import ProviderBase

class YahooProvider(ProviderBase):
    """
    Yahoo symbol provider adapter.
    Fetches US symbols and metadata from yfinance (auto discovery).
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[YahooProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Uses yfinance to enumerate all US stock tickers.
        Returns list of dicts: {symbol, exchange, companyName, sector, industry}
        Logs progress as symbols are collected.
        """
        import requests
        import time

        syms = []
        # Fetch NASDAQ
        try:
            response = requests.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&exchange=nasdaq&download=true", headers={"User-Agent": "Mozilla/5.0"})
            data = response.json()
            rows = data["data"]["rows"]
            for i, row in enumerate(rows):
                symbol = row["symbol"]
                name = row.get("name", "")
                if symbol and "Test Issue" not in name:
                    syms.append({
                        "symbol": symbol,
                        "exchange": "NASDAQ",
                        "companyName": name,
                        "sector": row.get("sector", ""),
                        "industry": row.get("industry", ""),
                    })
                if i > 0 and i % 1000 == 0:
                    self.log(f"Collected {i} NASDAQ symbols...")
            self.log(f"Loaded {len(rows)} NASDAQ symbols from NASDAQ.com API.")
        except Exception as e:
            self.log(f"Failed to fetch NASDAQ symbols: {e}")

        # Fetch NYSE
        try:
            response = requests.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&exchange=nyse&download=true", headers={"User-Agent": "Mozilla/5.0"})
            data = response.json()
            rows = data["data"]["rows"]
            for i, row in enumerate(rows):
                symbol = row["symbol"]
                name = row.get("name", "")
                if symbol and "Test Issue" not in name:
                    syms.append({
                        "symbol": symbol,
                        "exchange": "NYSE",
                        "companyName": name,
                        "sector": row.get("sector", ""),
                        "industry": row.get("industry", ""),
                    })
                if i > 0 and i % 1000 == 0:
                    self.log(f"Collected {i} NYSE symbols...")
            self.log(f"Loaded {len(rows)} NYSE symbols from NASDAQ.com API.")
        except Exception as e:
            self.log(f"Failed to fetch NYSE symbols: {e}")

        self.log(f"Total US symbols collected: {len(syms)}")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Fetches latest price, open, vwap for each symbol using Yahoo Finance API (yfinance).
        Returns list of dicts: [{symbol, c, o, vwap}]
        """
        import time
        from tbot_bot.config.env_bot import load_env_bot_config
        env = load_env_bot_config()
        sleep_time = float(env.get("UNIVERSE_SLEEP_TIME", 0.5))

        quotes = []
        for idx, symbol in enumerate(symbols):
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="2d")
                if hist.empty:
                    self.log(f"No Yahoo data for {symbol}")
                    continue
                bar = hist.iloc[-1]
                close = float(bar["Close"])
                open_ = float(bar["Open"])
                high = float(bar["High"])
                low = float(bar["Low"])
                vwap = (high + low + close) / 3 if all([high, low, close]) else close
                quotes.append({
                    "symbol": symbol,
                    "c": close,
                    "o": open_,
                    "vwap": vwap
                })
            except Exception as e:
                self.log(f"Exception fetching Yahoo quote for {symbol}: {e}")
                continue
            if idx > 0 and idx % 100 == 0:
                self.log(f"Fetched Yahoo quotes for {idx} symbols...")
            time.sleep(sleep_time)
        return quotes

    def fetch_universe_symbols(self, exchanges, min_price, max_price, min_cap, max_cap, blocklist, max_size) -> List[Dict]:
        """
        ProviderBase-compliant stub for universe build. Returns all from fetch_symbols.
        """
        try:
            symbols = self.fetch_symbols()
        except Exception as e:
            self.log(f"fetch_universe_symbols failed: {e}")
            return []
        return symbols

