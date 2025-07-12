# tbot_bot/screeners/providers/ibkr_provider.py
# IBKR provider adapter: fetches symbols and quotes via injected API keys/config
# 100% provider-registry and credential-management compliant.

import time
from typing import List, Dict, Optional

from tbot_bot.screeners.provider_base import ProviderBase

class IBKRProvider(ProviderBase):
    """
    IBKR provider adapter for symbol and quote fetching.
    All config and credentials must be injected at init (no env reads).
    """

    def __init__(self, config: Optional[Dict] = None, creds: Optional[Dict] = None):
        merged = {}
        if config:
            merged.update(config)
        if creds:
            merged.update(creds)
        super().__init__(merged)
        self.host = self.config.get("IBKR_HOST", "127.0.0.1")
        self.port = int(self.config.get("IBKR_PORT", 7497))
        self.client_id = int(self.config.get("IBKR_CLIENT_ID", 1))
        self.username = self.config.get("IBKR_USERNAME", "")
        self.password = self.config.get("IBKR_PASSWORD", "")
        self.timeout = int(self.config.get("API_TIMEOUT", 30))
        self.sleep = float(self.config.get("API_SLEEP", 0.2))
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()
        self._ib = None  # Only initialized if needed

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[IBKRProvider] {msg}")

    def _ensure_ibkr_client(self):
        if self._ib is not None:
            return self._ib
        try:
            from ib_insync import IB
            ib = IB()
            ib.connect(self.host, self.port, clientId=self.client_id, timeout=self.timeout)
            self._ib = ib
            self.log("IBKR API client connected.")
            return ib
        except ImportError:
            raise RuntimeError("ib_insync not installed. Cannot connect to IBKR.")
        except Exception as e:
            self.log(f"Failed to connect IBKR client: {e}")
            raise

    def fetch_symbols(self) -> List[Dict]:
        try:
            ib = self._ensure_ibkr_client()
            from ib_insync import Stock
            contracts = ib.reqScannerData(
                instrument="STK",
                locationCode="STK.US.MAJOR",
                scanCode="TOP_PERC_GAIN"
            )
            syms = []
            for con in contracts:
                symbol = getattr(con.contract, "symbol", None)
                exch = getattr(con.contract, "exchange", None) or "SMART"
                name = getattr(con, "description", "") or getattr(con, "longName", "")
                if symbol:
                    try:
                        syms.append({
                            "symbol": symbol.strip().upper(),
                            "exchange": exch,
                            "name": name
                        })
                    except Exception:
                        continue
            self.log(f"Fetched {len(syms)} IBKR equity symbols.")
            return syms
        except Exception as e:
            self.log(f"Error fetching IBKR symbols: {e}")
            return []

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        try:
            ib = self._ensure_ibkr_client()
            from ib_insync import Stock
            quotes = []
            for idx, symbol in enumerate(symbols):
                try:
                    contract = Stock(symbol, "SMART", "USD")
                    ticker = ib.reqMktData(contract, "", False, False)
                    time.sleep(self.sleep)
                    last = float(ticker.last or 0)
                    open_ = float(ticker.open or 0)
                    vwap = float(ticker.vwap or last or 0)
                    if last == 0 or open_ == 0:
                        self.log(f"Skipping {symbol}: missing price data")
                        continue
                    quotes.append({
                        "symbol": symbol,
                        "c": last,
                        "o": open_,
                        "vwap": vwap
                    })
                except Exception as e:
                    self.log(f"Error fetching quote for {symbol}: {e}")
                    continue
                if idx % 50 == 0 and idx > 0:
                    self.log(f"Fetched quotes for {idx} symbols...")
            return quotes
        except Exception as e:
            self.log(f"IBKR fetch_quotes failed: {e}")
            return []
