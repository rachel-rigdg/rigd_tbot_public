# tbot_bot/trading/trailing_stop.py
# Single source of truth for bot-enforced trailing stop math & state.

from dataclasses import dataclass
from typing import Optional, Callable  # (added for canonical API below)

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


def compute_trailing_exit_threshold(
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
    Return the trailing stop price threshold for the given position `side`.
      LONG  -> exit if price <= threshold
      SHORT -> exit if price >= threshold

    Combination rules:
      - If both percent and ATR are given, choose the *more conservative* threshold:
          LONG: max(candidates), SHORT: min(candidates)
      - If neither provided but peak/trough is known with pct (from state), use that.
      - If still insufficient and entry is known, default to 10% band vs entry.

    Clamps (if entry provided):
      - min_stop_pct prevents a too-tight stop (protects from micro whip).
      - max_stop_pct prevents a too-loose stop (caps risk).
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


def should_exit_by_trailing(
    current_price: float,
    **kwargs
) -> bool:
    """
    True if current_price has crossed the trailing stop threshold.
    kwargs must include `side` and any other params required by compute_trailing_exit_threshold.
      LONG  -> exit when current_price <= threshold
      SHORT -> exit when current_price >= threshold
    """
    if "side" not in kwargs:
        raise ValueError("should_exit_by_trailing requires 'side' in kwargs.")
    thr = compute_trailing_exit_threshold(current_price=current_price, **kwargs)
    side = str(kwargs["side"]).lower()
    cp = float(current_price)
    return (cp <= thr) if side == "long" else (cp >= thr)


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
    quantity: float | int | None = None,
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
