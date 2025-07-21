class AlpacaScreener(ScreenerBase):
    """
    Alpaca screener: loads eligible symbols from universe cache,
    fetches latest quotes from Alpaca, filters per strategy.
    Ensures output always flags fractional eligibility.
    """
    def __init__(self, *args, strategy=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.strategy = strategy

    def fetch_live_quotes(self, symbols):
        """
        Fetches latest price/open/vwap for each symbol using Alpaca API.
        Returns list of dicts: [{"symbol":..., "c":..., "o":..., "vwap":...}, ...]
        """
        quotes = []
        for idx, symbol in enumerate(symbols):
            url_bars = f"{SCREENER_URL.rstrip('/')}/v2/stocks/{symbol}/bars?timeframe=1Day&limit=1"
            auth = (SCREENER_USERNAME, SCREENER_PASSWORD) if SCREENER_USERNAME and SCREENER_PASSWORD else None
            try:
                bars_resp = requests.get(url_bars, headers={k: v for k, v in HEADERS.items() if v}, timeout=API_TIMEOUT, auth=auth)
                if bars_resp.status_code != 200:
                    log(f"Error fetching bars for {symbol}: HTTP {bars_resp.status_code}")
                    continue
                bars = bars_resp.json().get("bars", [])
                if not bars:
                    log(f"No bars data for {symbol}")
                    continue
                bar = bars[0]
                current = float(bar.get("c", 0))
                open_ = float(bar.get("o", 0))
                vwap = (bar["h"] + bar["l"] + bar["c"]) / 3 if all(k in bar for k in ("h", "l", "c")) else current
                quotes.append({
                    "symbol": symbol,
                    "c": current,
                    "o": open_,
                    "vwap": vwap
                })
            except Exception as e:
                log(f"Exception fetching quote for {symbol}: {e}")
                continue
            if idx % 50 == 0 and idx > 0:
                log(f"Fetched {idx} quotes...")
            time.sleep(0.2)
        return quotes

    def run_screen(self, pool_size=15):
        """
        Returns the full, ranked pool of symbol candidates (not filtered by final cut).
        pool_size: number of symbols to return (CANDIDATE_MULTIPLIER x MAX_TRADES from strategy).
        """
        universe = load_universe_cache()
        all_symbols = [s["symbol"] for s in universe][:pool_size * 2]
        quotes = self.fetch_live_quotes(all_symbols)
        strategy = self.strategy or self.env.get("STRATEGY_NAME", "open")
        gap_key = f"MAX_GAP_PCT_{strategy.upper()}"
        min_cap_key = f"MIN_MARKET_CAP_{strategy.upper()}"
        max_cap_key = f"MAX_MARKET_CAP_{strategy.upper()}"
        max_gap = float(self.env.get(gap_key, 0.1))
        min_cap = float(self.env.get(min_cap_key, 2e9))
        max_cap = float(self.env.get(max_cap_key, 1e10))

        try:
            universe_cache = {s["symbol"]: s for s in load_universe_cache()}
        except Exception:
            universe_cache = {}

        price_candidates = []
        for q in quotes:
            symbol = q["symbol"]
            current = float(q.get("c", 0))
            open_ = float(q.get("o", 0))
            vwap = float(q.get("vwap", 0))
            if current <= 0 or open_ <= 0 or vwap <= 0:
                continue
            mc = universe_cache.get(symbol, {}).get("marketCap", 0)
            exch = universe_cache.get(symbol, {}).get("exchange", "US")
            # Fractional enforcement: always present in result
            is_fractional = bool(universe_cache.get(symbol, {}).get("isFractional", FRACTIONAL))
            price_candidates.append({
                "symbol": symbol,
                "lastClose": current,
                "marketCap": mc,
                "exchange": exch,
                "isFractional": is_fractional,
                "price": current,
                "vwap": vwap,
                "open": open_
            })

        filtered = core_filter_symbols(
            price_candidates,
            exchanges=["US"],
            min_price=MIN_PRICE,
            max_price=MAX_PRICE,
            min_market_cap=min_cap,
            max_market_cap=max_cap,
            blocklist=None,
            max_size=pool_size * 2
        )

        results = []
        for q in price_candidates:
            if not any(f["symbol"] == q["symbol"] for f in filtered):
                continue
            symbol = q["symbol"]
            current = q["price"]
            open_ = q["open"]
            vwap = q["vwap"]
            gap = abs((current - open_) / open_) if open_ else 0
            if gap > max_gap:
                continue
            momentum = abs(current - open_) / open_
            results.append({
                "symbol": symbol,
                "price": current,
                "vwap": vwap,
                "momentum": momentum,
                "is_fractional": q["isFractional"]
            })
        results.sort(key=lambda x: x["momentum"], reverse=True)
        log_event("alpaca_screener", f"run_screen returned {len(results[:pool_size])} candidates")
        return results[:pool_size]

    def filter_candidates(self, quotes):
        """
        DEPRECATED: Returns a filtered, sorted candidate list for legacy modules.
        """
        strategy = self.strategy or self.env.get("STRATEGY_NAME", "open")
        gap_key = f"MAX_GAP_PCT_{strategy.upper()}"
        min_cap_key = f"MIN_MARKET_CAP_{strategy.upper()}"
        max_cap_key = f"MAX_MARKET_CAP_{strategy.upper()}"
        max_gap = float(self.env.get(gap_key, 0.1))
        min_cap = float(self.env.get(min_cap_key, 2e9))
        max_cap = float(self.env.get(max_cap_key, 1e10))
        limit = int(self.env.get("SCREENER_LIMIT", 3))

        try:
            universe_cache = {s["symbol"]: s for s in load_universe_cache()}
        except Exception:
            universe_cache = {}

        price_candidates = []
        for q in quotes:
            symbol = q["symbol"]
            current = float(q.get("c", 0))
            open_ = float(q.get("o", 0))
            vwap = float(q.get("vwap", 0))
            if current <= 0 or open_ <= 0 or vwap <= 0:
                continue
            mc = universe_cache.get(symbol, {}).get("marketCap", 0)
            exch = universe_cache.get(symbol, {}).get("exchange", "US")
            is_fractional = bool(universe_cache.get(symbol, {}).get("isFractional", FRACTIONAL))
            price_candidates.append({
                "symbol": symbol,
                "lastClose": current,
                "marketCap": mc,
                "exchange": exch,
                "isFractional": is_fractional,
                "price": current,
                "vwap": vwap,
                "open": open_
            })

        filtered = core_filter_symbols(
            price_candidates,
            exchanges=["US"],
            min_price=MIN_PRICE,
            max_price=MAX_PRICE,
            min_market_cap=min_cap,
            max_market_cap=max_cap,
            blocklist=None,
            max_size=limit
        )

        results = []
        for q in price_candidates:
            if not any(f["symbol"] == q["symbol"] for f in filtered):
                continue
            symbol = q["symbol"]
            current = q["price"]
            open_ = q["open"]
            vwap = q["vwap"]
            gap = abs((current - open_) / open_) if open_ else 0
            if gap > max_gap:
                continue
            momentum = abs(current - open_) / open_
            results.append({
                "symbol": symbol,
                "price": current,
                "vwap": vwap,
                "momentum": momentum,
                "is_fractional": q["isFractional"]
            })
        results.sort(key=lambda x: x["momentum"], reverse=True)
        log_event("alpaca_screener", f"filter_candidates returned {len(results)} candidates (legacy mode)")
        return results
