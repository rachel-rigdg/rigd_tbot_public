# tbot_bot/trading/holdings_utils.py
# Helper functions for allocation calculations, broker integration, audit logging, and COA posting.

import os
import math
from decimal import Decimal, ROUND_DOWN
from tbot_bot.support.utils_log import get_logger
from tbot_bot.config.env_bot import load_env_var
from tbot_bot.support.holdings_secrets import load_holdings_secrets, save_holdings_secrets


log = get_logger(__name__)

def parse_etf_allocations(etf_list_str):
    """Parses HOLDINGS_ETF_LIST string into dict: {'SCHD': 50, 'SCHY': 50}"""
    etfs = {}
    parts = etf_list_str.split(',')
    for part in parts:
        symbol, pct = part.strip().split(':')
        etfs[symbol.strip()] = float(pct)
    return etfs

def compute_target_cash(account_value, float_pct):
    """Returns target float value (e.g. 10% of account)."""
    return round(account_value * (float_pct / 100), 2)

def compute_cash_deficit(account_value, float_pct, current_cash):
    """Returns delta needed to reach float target."""
    target = compute_target_cash(account_value, float_pct)
    return round(target - current_cash, 2)

def compute_realized_tax_cut(realized_gain, tax_pct):
    """Returns the tax reserve from a realized gain."""
    return round(realized_gain * (tax_pct / 100), 2)

def compute_post_tax_payroll_cut(realized_gain, tax_cut, payroll_pct):
    """Returns the payroll reserve from remaining post-tax gain."""
    post_tax = realized_gain - tax_cut
    return round(post_tax * (payroll_pct / 100), 2)

def round_down_shares(amt, price):
    """Returns fractional shares (rounded down to nearest supported lot size)."""
    if price == 0:
        return 0
    shares = Decimal(amt) / Decimal(price)
    return float(shares.quantize(Decimal('0.0001'), rounding=ROUND_DOWN))

def compute_rebalance_orders(current_holdings, etf_targets, account_value):
    """Returns list of rebalance actions: [{'symbol': 'SCHD', 'action': 'buy', 'amount': 500.0}, ...]"""
    rebalance_orders = []
    for symbol, target_pct in etf_targets.items():
        target_value = account_value * (target_pct / 100)
        current_value = current_holdings.get(symbol, 0.0)
        delta = round(target_value - current_value, 2)
        if abs(delta) < 1:
            continue
        rebalance_orders.append({
            'symbol': symbol,
            'action': 'buy' if delta > 0 else 'sell',
            'amount': abs(delta)
        })
    return rebalance_orders

def compute_etf_holdings(broker):
    """
    Fetches ETF holdings from the broker, returns {symbol: value}.
    """
    try:
        holdings = broker.get_etf_holdings()
        log.info(f"Computed ETF holdings: {holdings}")
        return holdings
    except Exception as e:
        log.error(f"Error computing ETF holdings: {e}")
        return {}

def record_reserve_split(tax_cut, payroll_cut, user="system"):
    """
    Posts tax and payroll reserve splits to persistent holdings secrets and to the COA.
    """
    secrets = load_holdings_secrets()
    secrets['last_tax_reserve'] = tax_cut
    secrets['last_payroll_reserve'] = payroll_cut
    save_holdings_secrets(secrets, user, reason="reserve_split")
    # Post split to COA as per accounting/compliance spec
    post_reserve_split(tax_cut=tax_cut, payroll_cut=payroll_cut, user=user)
    log.info(f"Posted reserve split: Tax={tax_cut}, Payroll={payroll_cut}")

def trigger_manual_rebalance():
    """Stub to be replaced with actual rebalance call trigger."""
    log.info("Manual rebalance trigger requested")
    return {"status": "manual rebalance triggered"}
