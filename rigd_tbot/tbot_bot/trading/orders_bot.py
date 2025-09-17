# tbot_bot/trading/orders_bot.py
# Submit, modify, or cancel broker orders

"""
Creates and sends orders through the broker API interface.
Handles market orders and trailing stop-loss logic based on config.

TEST_MODE behavior:
- When test_mode.flag exists, NO live broker APIs are called.
- Orders are simulated as immediately filled and logged with "test_mode": True.
- Trailing stops are simulated (metadata returned) and must be enforced by the caller's monitoring loop.

LIVE behavior:
- After primary order placement, if trailing stops are requested and supported by the broker,
  a native trailing stop order is placed with the correct direction.
- If the broker does not support native trailing stops, metadata is returned so the runtime
  can enforce trailing exits by monitoring peak/trough and triggering exits.

NOTE:
- Runtime trailing-stop math (threshold computation & trigger checks) is centralized in
  tbot_bot/trading/trailing_stop.py. This module re-exports those helpers so existing
  call sites that import from orders_bot keep working without change.
"""

from pathlib import Path
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.utils_time import utc_now
from tbot_bot.support.utils_log import log_event
from tbot_bot.support.decrypt_secrets import decrypt_json

# --- Centralized trailing-stop helpers (re-exported here for backward compatibility) ---
from tbot_bot.trading.trailing_stop import (
    compute_trailing_exit_threshold as _ts_compute_trailing_exit_threshold,
    should_exit_by_trailing as _ts_should_exit_by_trailing,
)

# Lazy import of broker API to allow test-mode bypass without importing network libs
def _get_broker_api():
    from tbot_bot.broker import broker_api
    return broker_api

config = get_bot_config()
MAX_RISK_PER_TRADE = float(config.get("MAX_RISK_PER_TRADE", 0.025))
FRACTIONAL = bool(config.get("FRACTIONAL", True))
MIN_PRICE = float(config.get("MIN_PRICE", 5))
MAX_PRICE = float(config.get("MAX_PRICE", 100))

CONTROL_DIR = Path(__file__).resolve().parents[2] / "control"
TEST_MODE_FLAG = CONTROL_DIR / "test_mode.flag"

# Retrieve BROKER_CODE (BROKER_NAME) from broker_credentials.json.enc (not .env_bot)
broker_creds = decrypt_json("broker_credentials")
BROKER_NAME = broker_creds.get("BROKER_CODE", "ALPACA").lower()


def _is_test_mode_active() -> bool:
    return TEST_MODE_FLAG.exists()


def _calc_qty(capital: float, price: float, fractional: bool) -> float:
    return (capital / price) if fractional else int(capital / price)


def _validate_price_bounds(symbol: str, price: float) -> bool:
    if price < MIN_PRICE or price > MAX_PRICE:
        log_event("orders_bot", f"Price out of bounds for {symbol}: {price}")
        return False
    return True


def _supports_native_trailing() -> bool:
    try:
        api = _get_broker_api()
        fn = getattr(api, "supports_trailing_stops", None)
        return bool(fn() if callable(fn) else False)
    except Exception:
        return False


def _place_market_order_live(order: dict) -> dict | None:
    try:
        api = _get_broker_api()
        place_order = getattr(api, "place_order", None)
        if not callable(place_order):
            log_event("orders_bot", "Broker API missing place_order()")
            return None
        resp = place_order(order)
        if isinstance(resp, dict) and resp.get("error"):
            log_event("orders_bot", f"Order failed: {resp}")
            return None
        return order
    except Exception as e:
        log_event("orders_bot", f"Exception in _place_market_order_live: {e}")
        return None


def _place_exit_order_live(order: dict) -> dict | None:
    try:
        api = _get_broker_api()
        close_position = getattr(api, "close_position", None)
        if not callable(close_position):
            log_event("orders_bot", "Broker API missing close_position()")
            return None
        resp = close_position(order)
        if isinstance(resp, dict) and resp.get("error"):
            log_event("orders_bot", f"Exit order failed: {resp}")
            return None
        return order
    except Exception as e:
        log_event("orders_bot", f"Exception in _place_exit_order_live: {e}")
        return None


def _place_native_trailing_stop(symbol: str, side_open: str, qty: float, trail_pct: float, strategy: str | None):
    """
    Places a native trailing stop if the broker supports it.

    For a LONG entry (side_open == 'buy'): place a SELL trailing stop that triggers when price falls by trail_pct from peak.
    For a SHORT entry (side_open == 'sell'): place a BUY trailing stop that triggers when price rises by trail_pct from trough.

    trail_pct is a fraction (e.g., 0.02 for 2%).
    """
    try:
        api = _get_broker_api()
        place_trailing = getattr(api, "place_trailing_stop", None)
        if not callable(place_trailing):
            return {"ok": False, "reason": "no_api"}

        trail_side = "sell" if side_open == "buy" else "buy"
        # Many brokers take percent as whole percent (e.g., 2 for 2%); normalize both ways by exposing both fields.
        payload = {
            "symbol": symbol,
            "qty": round(float(qty), 6),
            "side": trail_side,
            "trail_percent": round(trail_pct * 100, 4),  # 2.0 for 2%
            "trail_pct_fraction": round(trail_pct, 6),   # 0.02 for 2%
            "strategy": strategy or "",
            "time": utc_now().isoformat(),
        }
        resp = place_trailing(payload)
        if isinstance(resp, dict) and resp.get("error"):
            return {"ok": False, "reason": "api_error", "resp": resp}
        return {"ok": True, "payload": payload}
    except Exception as e:
        return {"ok": False, "reason": f"exception: {e}"}


def create_order(symbol: str,
                 side: str,
                 capital: float,
                 price: float,
                 stop_loss_pct: float = 0.02,
                 strategy: str | None = None,
                 use_trailing_stop: bool = True) -> dict | None:
    """
    Create and submit a new order.

    :param symbol: str, stock ticker
    :param side: str, 'buy' or 'sell'
    :param capital: float, allocated capital (USD)
    :param price: float, current market price
    :param stop_loss_pct: float, trailing stop loss as fraction (e.g., 0.02 for 2%)
    :param strategy: str, strategy name
    :param use_trailing_stop: bool, request broker/native trailing if available
    :return: dict with order metadata or None if failed

    Trailing stop semantics (spec-compliant and centralized via trailing_stop.py):
      - LONG (side='buy'): exit when price falls 2% below the highest since entry (peak * (1 - pct)).
      - SHORT-like (side='sell'): exit when price rises 2% above the lowest since entry (trough * (1 + pct)).
        (When strategies use inverse ETFs but call side='buy', they should still pass use_trailing_stop=True;
         runtime monitoring should treat those as LONG positions on the ETF price stream.)
    """
    # TEST_MODE stub: simulate success, NO live API calls
    if _is_test_mode_active():
        if not _validate_price_bounds(symbol, price):
            return None
        qty = _calc_qty(capital, price, FRACTIONAL)
        if qty <= 0:
            log_event("orders_bot", f"TEST_MODE simulated order rejected: Invalid quantity for {symbol} at {price}")
            return None
        order = {
            "symbol": symbol,
            "qty": round(qty, 6),
            "side": side,
            "type": "market",
            "strategy": strategy,
            "price": float(price),
            "total_value": round(qty * price, 2),
            "timestamp": utc_now().isoformat(),
            "broker": BROKER_NAME,
            "account": "test_mode",
            "test_mode": True,
            "trailing": {
                "requested": bool(use_trailing_stop and stop_loss_pct > 0),
                "native": False,  # simulated; runtime must enforce using peaks/troughs
                "stop_loss_pct": float(stop_loss_pct),
                # Directional rule for runtime enforcement:
                #   long: exit below peak*(1 - pct)
                #   short-like: exit above trough*(1 + pct)
                "rule": "long_drop_from_peak" if side == "buy" else "short_rise_from_trough",
            },
        }
        log_event("orders_bot", f"TEST_MODE simulated order placed: {order}")
        return order

    # LIVE path
    if not _validate_price_bounds(symbol, price):
        return None

    qty = _calc_qty(capital, price, FRACTIONAL)
    if qty <= 0:
        log_event("orders_bot", f"Invalid quantity computed for {symbol} at {price}")
        return None
    if not FRACTIONAL and qty < 1:
        log_event("orders_bot", f"Insufficient capital for full share of {symbol} at {price}")
        return None

    base_order = {
        "symbol": symbol,
        "qty": round(qty, 6),
        "side": side,
        "type": "market",
        "strategy": strategy,
        "price": float(price),
        "total_value": round(qty * price, 2),
        "timestamp": utc_now().isoformat(),
        "broker": BROKER_NAME,
        "account": "live",
    }

    placed = _place_market_order_live(base_order)
    if not placed:
        return None

    trailing_meta = {
        "requested": bool(use_trailing_stop and stop_loss_pct > 0),
        "native": False,
        "stop_loss_pct": float(stop_loss_pct),
        "rule": "long_drop_from_peak" if side == "buy" else "short_rise_from_trough",
        "result": None,
    }

    # Try native trailing stop if requested and supported
    if trailing_meta["requested"] and _supports_native_trailing():
        result = _place_native_trailing_stop(
            symbol=symbol,
            side_open=side,
            qty=qty,
            trail_pct=stop_loss_pct,
            strategy=strategy
        )
        trailing_meta["native"] = bool(result.get("ok"))
        trailing_meta["result"] = result

    order = dict(base_order)
    order["trailing"] = trailing_meta
    log_event("orders_bot", f"Order placed: {order}")
    return order


def exit_order(symbol: str,
               side: str,
               qty: float,
               strategy: str | None = None) -> dict | None:
    """
    Exit an open position (market close).

    :param symbol: str
    :param side: str, 'sell' (for long exits) or 'buy' (to cover short)
    :param qty: float or int
    :param strategy: optional label
    :return: dict with order metadata or None
    """
    # TEST_MODE stub: simulate success, NO live API calls
    if _is_test_mode_active():
        order = {
            "symbol": symbol,
            "qty": round(float(qty), 6),
            "side": side,
            "type": "market",
            "strategy": strategy,
            "timestamp": utc_now().isoformat(),
            "broker": BROKER_NAME,
            "account": "test_mode",
            "test_mode": True,
        }
        log_event("orders_bot", f"TEST_MODE simulated exit order placed: {order}")
        return order

    order = {
        "symbol": symbol,
        "qty": round(float(qty), 6),
        "side": side,
        "type": "market",
        "strategy": strategy,
        "timestamp": utc_now().isoformat(),
        "broker": BROKER_NAME,
        "account": "live",
    }

    placed = _place_exit_order_live(order)
    if not placed:
        return None

    log_event("orders_bot", f"Exit order placed: {order}")
    return order


# ---------------------------
# Re-exported helpers for runtime trailing enforcement (centralized in trailing_stop.py)
# ---------------------------

def compute_trailing_exit_threshold(entry_price: float, current_extreme: float, side_open: str, stop_loss_pct: float) -> float:
    """
    Thin wrapper that delegates to tbot_bot.trading.trailing_stop.compute_trailing_exit_threshold.
    Kept for backward compatibility with existing imports from orders_bot.
    """
    return _ts_compute_trailing_exit_threshold(entry_price, current_extreme, side_open, stop_loss_pct)


def should_exit_by_trailing(current_price: float, entry_price: float, side_open: str,
                            running_peak: float | None, running_trough: float | None,
                            stop_loss_pct: float) -> bool:
    """
    Thin wrapper that delegates to tbot_bot.trading.trailing_stop.should_exit_by_trailing.
    Kept for backward compatibility with existing imports from orders_bot.
    """
    return _ts_should_exit_by_trailing(current_price, entry_price, side_open, running_peak, running_trough, stop_loss_pct)
