# tbot_bot/screeners/providers/yahoo_provider.py
# Yahoo provider adapter: fetches symbols/prices via Yahoo Finance API (yfinance), supports injected config.
# 100% ProviderBase-compliant, stateless, config-injected only.

import os
from typing import List, Dict, Optional
import yfinance as yf

from tbot_bot.screeners.provider_base import ProviderBase

class YahooProvider(ProviderBase):
    """
    Yahoo symbol provider adapter.
    Fetches symbols and metadata from Yahoo Finance API using yfinance.
    Accepts injected config (may contain 'symbol_list', 'csv_path', 'LOG_LEVEL').
    """

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self.symbol_list = self.config.get("symbol_list")
        self.csv_path = self.config.get("csv_path", "yahoo_symbols.csv")
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[YahooProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        """
        Loads symbols from provided symbol list or Yahoo-exported CSV file (or compatible).
        Returns list of dicts: {symbol, exchange, companyName, sector, industry}
        """
        syms = []
        # Use provided list if given
        if self.symbol_list and isinstance(self.symbol_list, list):
            syms = [{"symbol": s.strip().upper()} for s in self.symbol_list if s.strip()]
            self.log(f"Loaded {len(syms)} symbols from provided symbol_list.")
            return syms

        path = self.csv_path
        if not os.path.isfile(path):
            raise FileNotFoundError(f"[YahooProvider] Symbol CSV not found at path: {path}")
        import csv
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("Symbol") or row.get("symbol")
                name = row.get("Name") or row.get("Company Name") or ""
                exch = row.get("Exchange", "US")
                sector = row.get("Sector", "")
                industry = row.get("Industry", "")
                if symbol and name and "Test Issue" not in name:
                    syms.append({
                        "symbol": symbol.strip().upper(),
                        "exchange": exch.strip().upper() if exch else "US",
                        "companyName": name.strip(),
                        "sector": sector.strip(),
                        "industry": industry.strip()
                    })
        self.log(f"Loaded {len(syms)} symbols from Yahoo CSV.")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        """
        Fetches latest price, open, vwap for each symbol using Yahoo Finance API (yfinance).
        Returns list of dicts: [{symbol, c, o, vwap}]
        """
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
            if idx % 50 == 0 and idx > 0:
                self.log(f"Fetched Yahoo quotes for {idx} symbols...")
        return quotes

    def fetch_universe_symbols(self, exchanges, min_price, max_price, min_cap, max_cap, blocklist, max_size) -> List[Dict]:
        """
        ProviderBase-compliant stub for universe build. Returns all from CSV or symbol_list if present.
        """
        try:
            symbols = self.fetch_symbols()
        except Exception as e:
            self.log(f"fetch_universe_symbols failed: {e}")
            return []
        return symbols
