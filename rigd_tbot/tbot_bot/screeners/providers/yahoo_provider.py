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
        print(f"[YahooProvider] {msg}")

    def fetch_symbols(self) -> List[Dict]:
        import requests
        import time

        syms = []
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
                print(f"SYMBOL[{i}]: {symbol} | {name}")
                if i > 0 and i % 100 == 0:
                    print(f"[YahooProvider] Collected {i} NASDAQ symbols...")
                time.sleep(0.01)
            print(f"[YahooProvider] Loaded {len(rows)} NASDAQ symbols from NASDAQ.com API.")
        except Exception as e:
            print(f"[YahooProvider] Failed to fetch NASDAQ symbols: {e}")

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
                print(f"SYMBOL[{i}]: {symbol} | {name}")
                if i > 0 and i % 100 == 0:
                    print(f"[YahooProvider] Collected {i} NYSE symbols...")
                time.sleep(0.01)
            print(f"[YahooProvider] Loaded {len(rows)} NYSE symbols from NASDAQ.com API.")
        except Exception as e:
            print(f"[YahooProvider] Failed to fetch NYSE symbols: {e}")

        print(f"[YahooProvider] Total US symbols collected: {len(syms)}")
        return syms

    def fetch_quotes(self, symbols: List[str]) -> List[Dict]:
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
                    print(f"[YahooProvider] No Yahoo data for {symbol}")
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
                print(f"QUOTE[{idx}]: {symbol} | Close: {close} Open: {open_} VWAP: {vwap}")
            except Exception as e:
                print(f"[YahooProvider] Exception fetching Yahoo quote for {symbol}: {e}")
                continue
            if idx > 0 and idx % 10 == 0:
                print(f"[YahooProvider] Fetched Yahoo quotes for {idx} symbols...")
            time.sleep(sleep_time)
        return quotes

    def fetch_universe_symbols(self, exchanges, min_price, max_price, min_cap, max_cap, blocklist, max_size) -> List[Dict]:
        try:
            symbols = self.fetch_symbols()
        except Exception as e:
            print(f"[YahooProvider] fetch_universe_symbols failed: {e}")
            return []
        return symbols

    def full_universe_build(self):
        import os, json, time
        from datetime import datetime
        from tbot_bot.screeners.screener_filter import filter_symbols, dedupe_symbols
        from tbot_bot.support.path_resolver import resolve_universe_cache_path, resolve_universe_partial_path, resolve_universe_log_path
        from tbot_bot.config.env_bot import load_env_bot_config

        env = load_env_bot_config()
        sleep_time = float(env.get("UNIVERSE_SLEEP_TIME", 0.5))
        exchanges = [e.strip().upper() for e in env.get("SCREENER_UNIVERSE_EXCHANGES", "NASDAQ,NYSE").split(",")]
        min_price = float(env.get("SCREENER_UNIVERSE_MIN_PRICE", 1))
        max_price = float(env.get("SCREENER_UNIVERSE_MAX_PRICE", 10000))
        min_cap = float(env.get("SCREENER_UNIVERSE_MIN_MARKET_CAP", 300_000_000))
        max_cap = float(env.get("SCREENER_UNIVERSE_MAX_MARKET_CAP", 10_000_000_000))
        max_size = int(env.get("SCREENER_UNIVERSE_MAX_SIZE", 2000))

        log_path = resolve_universe_log_path()
        unfiltered_path = "tbot_bot/output/screeners/symbol_universe.unfiltered.json"
        partial_path = resolve_universe_partial_path()
        final_path = resolve_universe_cache_path()
        batch_size = 100

        def logp(msg, details=None):
            now = datetime.utcnow().replace(tzinfo=None).isoformat() + "Z"
            rec = f"[{now}] {msg}"
            if details:
                rec += " | " + json.dumps(details)
            with open(log_path, "a", encoding="utf-8") as logf:
                logf.write(rec + "\n")
            print(rec)

        # Fresh build: overwrite files
        all_syms = self.fetch_symbols()
        n = len(all_syms)
        logp("Starting full_universe_build", {"total_symbols": n, "batch_size": batch_size})

        # Remove old files
        for f in [unfiltered_path, partial_path, final_path]:
            try: os.remove(f)
            except Exception: pass

        filtered_total = []
        for batch_idx in range(0, n, batch_size):
            batch = all_syms[batch_idx:batch_idx + batch_size]
            # Write batch to unfiltered (append mode)
            if os.path.exists(unfiltered_path):
                with open(unfiltered_path, "r", encoding="utf-8") as uf:
                    existing = json.load(uf).get("symbols", [])
            else:
                existing = []
            batch_combined = existing + batch
            with open(unfiltered_path, "w", encoding="utf-8") as uf:
                json.dump({"symbols": batch_combined}, uf, indent=2)
            logp("Wrote unfiltered batch", {"batch_start": batch_idx, "batch_size": len(batch)})

            # Filter this batch and append to partial
            filtered_batch = filter_symbols(
                batch,
                exchanges,
                min_price,
                max_price,
                min_cap,
                max_cap,
                blocklist=None,
                max_size=None
            )
            filtered_total.extend(filtered_batch)
            with open(partial_path, "w", encoding="utf-8") as pf:
                json.dump({
                    "schema_version": "1.0.0",
                    "build_timestamp_utc": datetime.utcnow().isoformat() + "Z",
                    "symbols": filtered_total
                }, pf, indent=2)
            logp("Wrote filtered batch", {"filtered_batch": len(filtered_batch), "total_filtered": len(filtered_total)})

            time.sleep(sleep_time)

        # Write final
        with open(final_path, "w", encoding="utf-8") as ff:
            json.dump({
                "schema_version": "1.0.0",
                "build_timestamp_utc": datetime.utcnow().isoformat() + "Z",
                "symbols": filtered_total
            }, ff, indent=2)
        logp("Wrote final universe", {"final_count": len(filtered_total)})

if __name__ == "__main__":
    p = YahooProvider({"LOG_LEVEL": "verbose"})
    p.full_universe_build()
