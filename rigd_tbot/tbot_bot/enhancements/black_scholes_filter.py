# tbot_bot/enhancements/black_scholes_filter.py
# Enhancement: Validates put/call option pricing using Black-Scholes-Merton model
# Globalized for multi-jurisdiction trading via {JURISDICTION_CODE}

import math
from datetime import datetime
from tbot_bot.support.utils_log import log_event  # UPDATED
from tbot_bot.config.env_bot import get_bot_config
from tbot_bot.support.path_resolver import get_bot_identity
from scipy.stats import norm

config = get_bot_config()
identity = get_bot_identity()

JURISDICTION_CODE = identity.get("JURISDICTION_CODE", "USA")

ENABLE_BSM_FILTER = config.get("ENABLE_BSM_FILTER", "true").lower() == "true"
MAX_BSM_DEVIATION = float(config.get("MAX_BSM_DEVIATION", 0.15))

# Jurisdiction-specific risk-free rates
RISK_FREE_RATES = {
    "USA": 0.045,   # US 1-year Treasury yield
    "EUR": 0.035,   # ECB yield curve estimate
    "GBR": 0.0475,  # UK Gilt short-term
    "CAN": 0.043,   # Canadian 1-year rate
    "AUS": 0.042,   # Australia short bond
    "JPN": 0.001,   # Japan near-zero rate
    "SGP": 0.038,   # Singapore
    "HKG": 0.041,   # Hong Kong
    "IND": 0.066,   # India
    "BRA": 0.092    # Brazil (high-rate economy)
}

RISK_FREE_RATE = RISK_FREE_RATES.get(JURISDICTION_CODE, 0.045)

def calculate_bsm_price(option_type, S, K, T, r, sigma):
    """
    Black-Scholes-Merton formula for European options.

    :param option_type: 'call' or 'put'
    :param S: Spot price of the underlying
    :param K: Strike price
    :param T: Time to expiration in years
    :param r: Risk-free rate
    :param sigma: Implied volatility (decimal)
    :return: Theoretical option price
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type.lower() == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    elif option_type.lower() == "put":
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    else:
        raise ValueError("option_type must be 'call' or 'put'")

def passes_bsm_filter(option_type, S, K, T_days, sigma, market_price, context=None):
    """
    Evaluate if market price is within acceptable deviation of theoretical BSM price.

    :param option_type: 'call' or 'put'
    :param S: underlying price
    :param K: strike price
    :param T_days: time to expiry (in days)
    :param sigma: implied volatility (decimal)
    :param market_price: quoted premium
    :param context: optional dict for logging context
    :return: True if within range, else False
    """
    if not ENABLE_BSM_FILTER:
        return True

    T = T_days / 365.0
    theoretical_price = calculate_bsm_price(option_type, S, K, T, RISK_FREE_RATE, sigma)
    deviation = abs(theoretical_price - market_price) / theoretical_price if theoretical_price > 0 else 1.0

    if deviation > MAX_BSM_DEVIATION:
        log_event(
            f"BSM_FILTER_REJECTED | JURIS={JURISDICTION_CODE} | {option_type.upper()} "
            f"S={S} K={K} T={T_days}d σ={sigma:.2f} "
            f"market={market_price:.2f} model={theoretical_price:.2f} "
            f"deviation={deviation:.2%} | context={context}"
        )
        return False
    return True

def is_trade_blocked_by_bsm(option_type, S, K, T_days, sigma, market_price, context=None):
    """
    Richer interface: Returns (blocked:bool, reason:str|None)
    Use in risk modules that want full diagnostics.
    """
    if not ENABLE_BSM_FILTER:
        return (False, None)

    T = T_days / 365.0
    theoretical_price = calculate_bsm_price(option_type, S, K, T, RISK_FREE_RATE, sigma)
    deviation = abs(theoretical_price - market_price) / theoretical_price if theoretical_price > 0 else 1.0

    if deviation > MAX_BSM_DEVIATION:
        reason = (
            f"BSM deviation {deviation:.2%} exceeds threshold "
            f"(market={market_price:.2f}, model={theoretical_price:.2f}, juris={JURISDICTION_CODE})"
        )
        log_event(
            f"BSM_FILTER_REJECTED | JURIS={JURISDICTION_CODE} | {option_type.upper()} "
            f"S={S} K={K} T={T_days}d σ={sigma:.2f} "
            f"market={market_price:.2f} model={theoretical_price:.2f} "
            f"deviation={deviation:.2%} | context={context}"
        )
        return (True, reason)
    return (False, None)
