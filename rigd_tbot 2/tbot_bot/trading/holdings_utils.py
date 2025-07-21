# tbot_bot/trading/holdings_utils.py
# Helper functions for allocation calculations, broker integration, audit logging, and LEDGER posting.
# All monetary actions in this module must result in a ledger entry and audit log.
# Any function that affects cash, reserve, or ETF allocation must be called via orchestration with user and audit context.

import os
import math
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from tbot_bot.support.utils_log import get_logger
from tbot_bot.config.env_bot import load_env_var
from tbot_bot.support.holdings_secrets import load_holdings_secrets, save_holdings_secrets

# Correct imports: LEDGER, not COA!
from tbot_bot.accounting.ledger import (
    post_tax_reserve_entry,
    post_payroll_reserve_entry,
    post_float_allocation_entry,
    post_rebalance_entry
)
from tbot_bot.reporting.audit_logger import audit_log_event
from tbot_bot.trading.holdings_manager import run_rebalance_cycle

log = get_logger(__name__)

def parse_etf_allocations(etf_list_str):
    """Parses ETF allocation string into dict: {'SCHD': 50, 'SCHY': 50}"""
    etfs = {}
    if not etf_list_str:
        return etfs
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

def record_reserve_split(tax_cut, payroll_cut, user="system", audit_reference=None):
    """
    Posts tax and payroll reserve splits to persistent holdings secrets, the LEDGER, and the audit log.
    """
    now_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    # Persist to holdings secrets (internal tracking only)
    secrets = load_holdings_secrets()
    secrets['last_tax_reserve'] = tax_cut
    secrets['last_payroll_reserve'] = payroll_cut
    save_holdings_secrets(secrets, user, reason="reserve_split")

    # --- Post to LEDGER, NOT COA ---
    post_tax_reserve_entry(amount=tax_cut, datetime_utc=now_utc, notes="Tax reserve split")
    post_payroll_reserve_entry(amount=payroll_cut, datetime_utc=now_utc, notes="Payroll reserve split")
    # Audit log event
    audit_log_event(
        event_type="reserve_split",
        user=user,
        reference=audit_reference,
        details={"tax_cut": tax_cut, "payroll_cut": payroll_cut}
    )
    log.info(f"Posted reserve split: Tax={tax_cut}, Payroll={payroll_cut}, User={user}, AuditRef={audit_reference}")

def record_float_allocation(amount, user="system", audit_reference=None):
    """
    Posts a float allocation event to the LEDGER and audit log.
    """
    now_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    post_float_allocation_entry(amount=amount, datetime_utc=now_utc, notes="Float allocation")
    audit_log_event(
        event_type="float_allocation",
        user=user,
        reference=audit_reference,
        details={"amount": amount}
    )
    log.info(f"Posted float allocation: Amount={amount}, User={user}, AuditRef={audit_reference}")

def record_rebalance(symbol, amount, action, user="system", audit_reference=None):
    """
    Posts a rebalance event to the LEDGER and audit log.
    """
    now_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    post_rebalance_entry(symbol=symbol, amount=amount, action=action, datetime_utc=now_utc, notes="Rebalance action")
    audit_log_event(
        event_type="rebalance",
        user=user,
        reference=audit_reference,
        details={"symbol": symbol, "amount": amount, "action": action}
    )
    log.info(f"Posted rebalance: {action} {amount} of {symbol}, User={user}, AuditRef={audit_reference}")

def trigger_manual_rebalance(user="system", audit_reference=None):
    """
    Triggers an immediate rebalance via holdings_manager.run_rebalance_cycle,
    posts to LEDGER and audit log, and returns the result.
    """
    log.info("Manual rebalance trigger requested")
    result = run_rebalance_cycle(user=user)
    # Audit log
    audit_log_event(
        event_type="manual_rebalance",
        user=user,
        reference=audit_reference,
        details={"status": "manual rebalance triggered", "result": result}
    )
    return {"status": "manual rebalance triggered", "result": result}
