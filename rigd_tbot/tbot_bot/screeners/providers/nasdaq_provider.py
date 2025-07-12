# tbot_bot/screeners/providers/nasdaq_provider.py
# NASDAQ provider adapter: fetches NASDAQ symbols and quotes via injected IBKR API credentials/config.
# 100% ProviderBase-compliant, stateless, config-injected only.

from typing import List, Dict, Optional
import time

from tbot_bot.screeners.provider_base import ProviderBase

class NasdaqProvider(ProviderBase):
    """
    NASDAQ provider adapter using IBKR API (via ib_insync).
    All config and credentials must be injected at init.
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
        self.client_id = int(self.config.get("IBKR_CLIENT_ID", 2))
        self.timeout = int(self.config.get("API_TIMEOUT", 30))
        self.sleep = float(self.config.get("API_SLEEP", 0.2))
        self.log_level = str(self.config.get("LOG_LEVEL", "silent")).lower()
        self._ib = None

    def log(self, msg):
        if self.log_level == "verbose":
            print(f"[NasdaqProvider] {msg}")

    def _ensure_ibkr_client(self):
        if self._ib is not None:
            return self._ib
        try:
            from ib_insync import IB
            ib = IB()
            ib.connect(self.host, self.port, clientId=self.client_id, timeout=self.timeout)
            self._ib = ib
            self.log("Connected to IBKR API.")
            return ib
        except ImportError:
            raise RuntimeError("ib_insync is not installed. Cannot fetch NASDAQ symbols via IBKR.")
        except Exception as e:
            self.log(f"Failed to connect to IBKR: {e}")
            raise

    def fetch_symbols(self) -> List[Dict]:
        try:
            ib = self._ensure_ibkr_client()
            from ib_insync import ScannerSubscription
            scan = ScannerSubscription()
            scan.instrument = "STK"
            scan.locationCode = "STK.NASDAQ"
            scan.scanCode = "MOST_ACTIVE"
            contracts = ib.reqScannerData(scan)
            syms = []
            for con in contracts:
                symbol = con.contract.symbol
                exch = con.contract.exchange or "NASDAQ"
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
            self.log(f"Fetched {len(syms)} NASDAQ symbols from IBKR.")
            return syms
        except Exception as e:
            self.log(f"Error fetching NASDAQ symbols: {e}")
            return []

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
        try:
            ib = self._ensure_ibkr_client()
            from ib_insync import Stock
            quotes = []
            for idx, symbol in enumerate(symbols):
                try:
                    contract = Stock(symbol, "NASDAQ", "USD")
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
                    self.log(f"Error fetching NASDAQ quote for {symbol}: {e}")
                    continue
                if idx % 50 == 0 and idx > 0:
                    self.log(f"Fetched NASDAQ quotes for {idx} symbols...")
            return quotes
        except Exception as e:
            self.log(f"Error in fetch_quotes: {e}")
            return []
