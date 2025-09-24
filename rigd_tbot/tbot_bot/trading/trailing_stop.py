# tbot_bot/trading/trailing_stop.py
# Single source of truth for bot-enforced trailing stop math & state.

from dataclasses import dataclass
from typing import Optional, Callable, Union  # (added Union for 3.7–3.9 compatibility)
from datetime import datetime, timezone  # (surgical) for pre-close tightening helpers

@dataclass
class TrailingStopState:
    side: str                 # "long" or "short" (use "short" also for inverse-ETF buys)
    pct: float                # 0.02 for 2%
    peak: float = 0.0         # highest seen since entry (long)
    trough: float = 10**12    # lowest seen since entry (short)
    active: bool = True       # allow disable if broker-native used

    def register_tick(self, price: float) -> None:
        if not self.active:
            return
        if self.side == "long":
            if price > self.peak:
                self.peak = price
        else:  # short / inverse-ETF
            if price < self.trough:
                self.trough = price

    def exit_trigger_price(self) -> Optional[float]:
        if not self.active:
            return None
        if self.side == "long" and self.peak > 0:
            return self.peak * (1.0 - self.pct)  # peak × 0.98
        if self.side != "long" and self.trough < 10**12:
            return self.trough * (1.0 + self.pct)  # trough × 1.02
        return None

    def should_exit(self, price: float) -> bool:
        t = self.exit_trigger_price()
        if t is None:
            return False
        if self.side == "long":
            return price <= t
        else:
            return price >= t


# === Canonical trailing-stop API (append-only; strategies import these symbols) ===
# Exposes:
#   - compute_trailing_exit_threshold(...)
#   - should_exit_by_trailing(...)
#
# Behavior:
#   * Works for long/short.
#   * Supports percent trailing and/or ATR-based trailing.
#   * Optional min/max stop bands vs entry.
#   * If TrailingStopState semantics are enough (peak/trough provided), we reuse them.

def _resolve_legacy_threshold_fn() -> Optional[Callable]:
    """
    If older projects defined a custom function name in this module, delegate to it.
    Keeps backward compatibility without shims in the router/strategies.
    """
    for cand in (
        "trailing_exit_threshold",
        "get_trailing_exit_threshold",
        "compute_trailing_exit",
        "make_trailing_exit_threshold",
        "compute_trailing_stop_threshold",
    ):
        fn = globals().get(cand)
        if callable(fn):
            return fn
    return None


def _compute_trailing_exit_threshold_kw(
    *,
    side: str,
    current_price: Optional[float] = None,
    entry_price: Optional[float] = None,
    peak_price: Optional[float] = None,
    trough_price: Optional[float] = None,
    trail_pct: Optional[float] = None,        # e.g., 0.05 for 5%
    atr: Optional[float] = None,               # ATR in price units
    atr_mult: Optional[float] = None,          # e.g., 3.0
    min_stop_pct: Optional[float] = None,      # clamp: not tighter than this (vs entry)
    max_stop_pct: Optional[float] = None       # clamp: not looser than this (vs entry)
) -> float:
    """
    Keyword-only core implementation (new API).
    """
    # Legacy delegation if present
    _legacy = _resolve_legacy_threshold_fn()
    if _legacy is not None:
        return _legacy(
            side=side,
            current_price=current_price,
            entry_price=entry_price,
            peak_price=peak_price,
            trough_price=trough_price,
            trail_pct=trail_pct,
            atr=atr,
            atr_mult=atr_mult,
            min_stop_pct=min_stop_pct,
            max_stop_pct=max_stop_pct,
        )

    if side is None or str(side).lower() not in {"long", "short"}:
        raise ValueError("side must be 'long' or 'short'")
    s_long = (str(side).lower() == "long")

    candidates = []

    # 1) Percent trailing from peak/trough if provided
    if (trail_pct is not None) and (trail_pct > 0):
        if s_long and peak_price:
            candidates.append(float(peak_price) * (1.0 - float(trail_pct)))
        elif (not s_long) and trough_price:
            candidates.append(float(trough_price) * (1.0 + float(trail_pct)))

    # 2) ATR-based trailing from *current* if provided
    if (atr is not None and atr > 0) and (atr_mult is not None and atr_mult > 0) and (current_price is not None):
        dist = float(atr) * float(atr_mult)
        if s_long:
            candidates.append(float(current_price) - dist)
        else:
            candidates.append(float(current_price) + dist)

    # 3) Reuse state-style trailing if peak/trough + pct looks valid (without ATR/explicit percent candidate)
    if not candidates and (trail_pct is not None) and trail_pct > 0:
        if s_long and peak_price and peak_price > 0:
            candidates.append(float(peak_price) * (1.0 - float(trail_pct)))
        if (not s_long) and trough_price and trough_price < 10**12:
            candidates.append(float(trough_price) * (1.0 + float(trail_pct)))

    # 4) Fallback to a 10% band vs entry if still nothing
    if not candidates and entry_price:
        e = float(entry_price)
        candidates.append(e * (0.90 if s_long else 1.10))

    if not candidates:
        raise ValueError("Insufficient data to compute trailing stop threshold.")

    # Combine conservatively
    threshold = max(candidates) if s_long else min(candidates)

    # Apply clamps vs entry (if provided)
    if entry_price:
        e = float(entry_price)
        if min_stop_pct is not None and min_stop_pct > 0:
            min_thr = e * (1.0 - float(min_stop_pct)) if s_long else e * (1.0 + float(min_stop_pct))
            threshold = max(threshold, min_thr) if s_long else min(threshold, min_thr)
        if max_stop_pct is not None and max_stop_pct > 0:
            max_thr = e * (1.0 - float(max_stop_pct)) if s_long else e * (1.0 + float(max_stop_pct))
            threshold = min(threshold, max_thr) if s_long else max(threshold, max_thr)

    return float(threshold)


def compute_trailing_exit_threshold(*args, **kwargs) -> float:
    """
    Backward-compatible public function.

    Supports TWO call styles:

      1) New keyword-only style:
         compute_trailing_exit_threshold(
             side="long"|"short",
             current_price=..., entry_price=..., peak_price=..., trough_price=...,
             trail_pct=..., atr=..., atr_mult=..., min_stop_pct=..., max_stop_pct=...
         )

      2) Legacy positional style (used by older code paths, e.g. orders_bot wrappers):
         compute_trailing_exit_threshold(entry_price, current_extreme, side_open, stop_loss_pct)

         where:
           - side_open is "buy"/"sell" or "long"/"short"
           - current_extreme is peak (long) or trough (short)
           - stop_loss_pct is a fraction (e.g., 0.02)
    """
    if kwargs:
        return _compute_trailing_exit_threshold_kw(**kwargs)

    # Legacy positional mapping
    if len(args) == 4:
        entry_price, current_extreme, side_open, stop_loss_pct = args
        side_open = str(side_open).lower()
        side = "long" if side_open in {"buy", "long"} else "short"
        peak_price = float(current_extreme) if side == "long" else None
        trough_price = float(current_extreme) if side == "short" else None
        return _compute_trailing_exit_threshold_kw(
            side=side,
            entry_price=float(entry_price) if entry_price is not None else None,
            peak_price=peak_price,
            trough_price=trough_price,
            trail_pct=float(stop_loss_pct) if stop_loss_pct is not None else None,
        )

    raise TypeError("compute_trailing_exit_threshold expects either keyword arguments or 4 legacy positional arguments.")


def should_exit_by_trailing(*args, **kwargs) -> bool:
    """
    Backward-compatible public function.

    Supports TWO call styles:

      1) New style:
         should_exit_by_trailing(
             current_price=..., side="long"|"short",
             entry_price=..., peak_price=..., trough_price=...,
             trail_pct=..., atr=..., atr_mult=..., min_stop_pct=..., max_stop_pct=...
         )

      2) Legacy positional style (used by older code paths, e.g. orders_bot wrappers):
         should_exit_by_trailing(current_price, entry_price, side_open, running_peak, running_trough, stop_loss_pct)
    """
    # New style (kwargs)
    if kwargs:
        if "side" not in kwargs:
            raise ValueError("should_exit_by_trailing requires 'side' in kwargs.")
        if "current_price" not in kwargs:
            raise ValueError("should_exit_by_trailing requires 'current_price' in kwargs.")
        thr = _compute_trailing_exit_threshold_kw(**kwargs)
        side = str(kwargs["side"]).lower()
        cp = float(kwargs["current_price"])
        return (cp <= thr) if side == "long" else (cp >= thr)

    # Legacy positional
    if len(args) == 6:
        current_price, entry_price, side_open, running_peak, running_trough, stop_loss_pct = args
        side_open = str(side_open).lower()
        side = "long" if side_open in {"buy", "long"} else "short"
        peak_price = float(running_peak) if running_peak is not None else None
        # (surgical) fix variable name typo: running_trrough -> running_trough
        trough_price = float(running_trough) if running_trough is not None else None
        thr = _compute_trailing_exit_threshold_kw(
            side=side,
            current_price=float(current_price),
            entry_price=float(entry_price) if entry_price is not None else None,
            peak_price=peak_price,
            trough_price=trough_price,
            trail_pct=float(stop_loss_pct) if stop_loss_pct is not None else None,
        )
        cp = float(current_price)
        return (cp <= thr) if side == "long" else (cp >= thr)

    raise TypeError("should_exit_by_trailing expects either keyword arguments or 6 legacy positional arguments.")


# Back-compat aliases (only if older code imports these names)
trailing_exit_threshold = globals().get("trailing_exit_threshold", compute_trailing_exit_threshold)
get_trailing_exit_threshold = globals().get("get_trailing_exit_threshold", compute_trailing_exit_threshold)


# === Broker-preferred helpers (opt-in) =========================================
# These helpers let strategies prefer broker-native trailing stops when supported,
# and fall back to local state-based monitoring otherwise. They DO NOT place entry orders.

def broker_supports_trailing_stop(broker, symbol: str, side: str) -> bool:
    """
    Return True if the active broker adapter advertises native trailing-stop support
    for the given (symbol, side). Adapters should implement:
        supports_trailing_stop(symbol: str, side: str) -> bool
    """
    try:
        fn = getattr(broker, "supports_trailing_stop", None)
        if callable(fn):
            return bool(fn(symbol, side))
    except Exception:
        pass
    return False


def place_or_prepare_trailing_stop(
    *,
    broker,
    symbol: str,
    side: str,                     # "long" or "short" (use "short" for inverse-ETF buys)
    quantity: Optional[Union[float, int]] = None,
    trail_pct: Optional[float] = None,      # prefer pct; adapters may convert to amount
    trail_amount: Optional[float] = None,   # optional alternative
    time_in_force: str = "day",
    entry_price: Optional[float] = None,
    activate_local: bool = True,
) -> dict:
    """
    Prefer broker-native trailing stop; else return a local TrailingStopState.

    Returns dict:
      { "placed": True,  "state": None }               # broker-native placed
      { "placed": False, "state": TrailingStopState }  # local fallback; caller must poll register_tick/should_exit

    NOTE: This function does not place the entry order. Call it immediately after entry
    (with entry_price if you have it) so local state can seed peak/trough correctly.
    """
    # Try broker-native first
    if broker_supports_trailing_stop(broker, symbol, side):
        try:
            place_fn = getattr(broker, "place_trailing_stop_order", None)
            if callable(place_fn):
                place_fn(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    trail_pct=trail_pct,
                    trail_amount=trail_amount,
                    time_in_force=time_in_force,
                )
                return {"placed": True, "state": None}
        except Exception:
            # fall through to local if broker throws
            pass

    # Local fallback
    state = TrailingStopState(side=side, pct=float(trail_pct or 0.0), active=bool(activate_local))
    if entry_price is not None:
        # initialize peak/trough from known fill
        if side == "long":
            state.peak = float(entry_price)
        else:
            state.trough = float(entry_price)
    return {"placed": False, "state": state}


# === Per-strategy trailing % helpers (append-only; used by strategies) =========

def get_strategy_trail_pct(strategy: str, config: dict, default_pct: float = 0.02) -> float:
    """
    Read a per-strategy trailing stop percent from config, with sensible fallbacks.
    strategy: "open" | "mid" | "close"
    """
    key_map = {
        "open": "TRAIL_PCT_OPEN",
        "mid": "TRAIL_PCT_MID",
        "close": "TRAIL_PCT_CLOSE",
    }
    key = key_map.get(str(strategy).lower())
    if key and (key in config):
        try:
            return float(config.get(key))
        except Exception:
            pass
    # global fallback
    try:
        return float(config.get("TRADING_TRAILING_STOP_PCT", default_pct))
    except Exception:
        return float(default_pct)


def _parse_hhmmss_utc(hhmmss: str, ref_date: datetime) -> datetime:
    """
    Parse 'HH:MM' or 'HH:MM:SS' (UTC) into a timezone-aware datetime on ref_date.
    """
    parts = str(hhmmss).strip().split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    return ref_date.replace(hour=h, minute=m, second=s, microsecond=0)


def get_tightened_trailing_pct(
    *,
    base_pct: float,
    now_utc: datetime,
    market_close_utc: str,
    hard_close_buffer_s: int = 150,
    tighten_factor: float = 0.5
) -> float:
    """
    If we're within `hard_close_buffer_s` seconds of MARKET_CLOSE_UTC, tighten the trailing stop
    by `tighten_factor` (e.g., 0.5 -> half as loose). Otherwise return base_pct unchanged.

    All times should be UTC; `now_utc` must be timezone-aware.
    """
    try:
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        close_dt = _parse_hhmmss_utc(market_close_utc, now_utc.astimezone(timezone.utc))
        # if already past close time today, don't tighten (no negative-day rollover here)
        delta = (close_dt - now_utc).total_seconds()
        if 0 <= delta <= int(hard_close_buffer_s):
            # tighten, but keep a sane floor (don’t go to 0)
            tightened = max(0.0005, float(base_pct) * float(tighten_factor))
            return tightened
        return float(base_pct)
    except Exception:
        # On any parsing/logic error, fail safe to base pct
        return float(base_pct)
