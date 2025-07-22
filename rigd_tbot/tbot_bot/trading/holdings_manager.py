# tbot_bot/trading/holdings_manager.py
# Persistent process for all holdings ops: float top-up, rebalance, tax/payroll allocation.
# Loads config from holdings_secrets, routes all trades via broker_api.
# Writes to audit log and ledger. No business logic lives in the supervisor.

import time
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from tbot_bot.trading.holdings_utils import (
    parse_etf_allocations,
    compute_cash_deficit,
    compute_realized_tax_cut,
    compute_post_tax_payroll_cut,
    compute_rebalance_orders,
    simulate_rebalance_compliance,
)
from tbot_bot.support.holdings_secrets import load_holdings_secrets, save_holdings_secrets
from tbot_bot.support.utils_log import get_logger, log_event
from tbot_bot.broker.broker_api import get_active_broker
from tbot_bot.support.path_resolver import get_bot_state_path
from tbot_bot.support.bootstrap_utils import is_first_bootstrap
from tbot_bot.reporting.audit_logger import audit_log_event

log = get_logger(__name__)

POLL_INTERVAL = 60  # seconds between checks, can be made configurable

def _is_bot_initialized():
    if is_first_bootstrap(quiet_mode=True):
        return False
    state_path = get_bot_state_path()
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = f.read().strip()
        return state not in ("initialize", "provisioning", "bootstrapping")
    except Exception:
        return False

def _is_broker_configured():
    try:
        broker = get_active_broker()
        _ = broker.get_account_value()
        return True
    except Exception as e:
        log.error(f"Broker not configured or not provisioned: {e}")
        return False

def _should_topup_float(account_value, float_pct, current_cash):
    deficit = compute_cash_deficit(account_value, float_pct, current_cash)
    return deficit > 1

def _should_rebalance(holdings_cfg):
    rebalance_interval = int(holdings_cfg.get("HOLDINGS_REBALANCE_INTERVAL", 3))
    next_rebalance_due = holdings_cfg.get("NEXT_REBALANCE_DUE")
    try:
        if next_rebalance_due:
            rebalance_due_date = datetime.fromisoformat(next_rebalance_due).date()
            if datetime.utcnow().date() >= rebalance_due_date:
                return True
    except Exception as e:
        log.warning(f"Rebalance date check failed: {e}")
    return False

def _mark_rebalance_complete(holdings_cfg):
    rebalance_interval = int(holdings_cfg.get("HOLDINGS_REBALANCE_INTERVAL", 3))
    next_due = datetime.utcnow().date() + relativedelta(months=rebalance_interval)
    save_holdings_secrets({**holdings_cfg, "NEXT_REBALANCE_DUE": next_due.isoformat()}, user="holdings_manager", reason="rebalance_complete")

def _compliance_preview_or_abort(holdings, etf_targets, account_value):
    compliance_ok, preview = simulate_rebalance_compliance(holdings, etf_targets, account_value)
    if not compliance_ok:
        log.error(f"Rebalance/compliance preview failed: {preview}")
        log_event("holdings_compliance_block", user="holdings_manager", details={"reason": preview})
        audit_log_event("holdings_compliance_block", user="holdings_manager", reference=None, details={"reason": preview})
        return False
    return True

def get_holdings_status():
    """
    Returns status for the UI table: account value, cash, next rebalance, and ETF holdings rows.
    """
    broker = get_active_broker()
    account_value = broker.get_account_value()
    cash = broker.get_cash_balance()
    holdings_cfg = load_holdings_secrets()
    etf_cfg = holdings_cfg.get("HOLDINGS_ETF_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)
    next_rebalance_due = holdings_cfg.get("NEXT_REBALANCE_DUE")
    etf_holdings = []
    try:
        live = broker.get_etf_positions()  # Must return list of dicts per ETF: symbol, units, purchase_price, market_price, market_value, pl, total_gain_loss
        for etf in live:
            symbol = etf.get("symbol")
            etf_holdings.append({
                "symbol": symbol,
                "allocation_pct": etf_targets.get(symbol, 0),
                "purchase_price": etf.get("purchase_price", 0),
                "units": etf.get("units", 0),
                "market_price": etf.get("market_price", 0),
                "market_value": etf.get("market_value", 0),
                "unrealized_pl": etf.get("unrealized_pl", 0),
                "total_gain_loss": etf.get("total_gain_loss", 0)
            })
    except Exception as e:
        log.error(f"Failed to fetch ETF holdings: {e}")

    return {
        "account_value": account_value,
        "cash": cash,
        "next_rebalance_due": next_rebalance_due,
        "etf_holdings": etf_holdings
    }

def perform_holdings_cycle(realized_gains: float = 0.0, user: str = "holdings_manager"):
    if not _is_bot_initialized():
        log.warning("Holdings manager: Bot not initialized/provisioned/bootstrapped.")
        return
    if not _is_broker_configured():
        log.warning("Holdings manager: No broker is configured or provisioned yet.")
        return

    broker = get_active_broker()
    holdings_cfg = load_holdings_secrets()
    float_pct = float(holdings_cfg.get("HOLDINGS_FLOAT_TARGET_PCT", 10))
    tax_pct = float(holdings_cfg.get("HOLDINGS_TAX_RESERVE_PCT", 20))
    payroll_pct = float(holdings_cfg.get("HOLDINGS_PAYROLL_PCT", 10))
    etf_cfg = holdings_cfg.get("HOLDINGS_ETF_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)

    account_value = broker.get_account_value()
    current_cash = broker.get_cash_balance()

    # === Step 0: Conditional rebalance if due ===
    if _should_rebalance(holdings_cfg):
        holdings = broker.get_etf_holdings()
        if _compliance_preview_or_abort(holdings, etf_targets, account_value):
            perform_rebalance_cycle(user)
            _mark_rebalance_complete(holdings_cfg)
        else:
            log.warning("Rebalance blocked for compliance, not executed.")
            return

    # === Step 1: Top-up float (sell ETFs if needed) ===
    deficit = compute_cash_deficit(account_value, float_pct, current_cash)
    if deficit > 1:
        holdings = broker.get_etf_holdings()
        sorted_by_value = sorted(holdings.items(), key=lambda x: -x[1])
        for symbol, value in sorted_by_value:
            if value < 1:
                continue
            sell_amt = min(deficit, value)
            broker.place_order(symbol, "sell", sell_amt)
            deficit -= sell_amt
            log.info(f"Topped up cash by selling {sell_amt} of {symbol}")
            log_event("holdings_float_topup", user=user, details={
                "symbol": symbol, "amount": sell_amt, "reason": "float_topup"
            })
            audit_log_event("holdings_float_topup", user=user, reference=symbol, details={"amount": sell_amt, "reason": "float_topup"})
            if deficit <= 1:
                break

    # === Step 2: Allocate tax + payroll reserve ===
    tax_cut = compute_realized_tax_cut(realized_gains, tax_pct)
    payroll_cut = compute_post_tax_payroll_cut(realized_gains, tax_cut, payroll_pct)
    log.info(f"Tax Reserve: {tax_cut}, Payroll: {payroll_cut}")
    log_event("holdings_reserve_allocation", user=user, details={
        "tax_cut": tax_cut, "payroll_cut": payroll_cut
    })
    audit_log_event("holdings_reserve_allocation", user=user, reference=None, details={"tax_cut": tax_cut, "payroll_cut": payroll_cut})

    # === Step 3: Reinvest post-reserve remainder into target ETFs ===
    remainder = realized_gains - tax_cut - payroll_cut
    if remainder > 1:
        prices = {symbol: broker.get_price(symbol) for symbol in etf_targets}
        total_pct = sum(etf_targets.values())
        for symbol, pct in etf_targets.items():
            alloc_amt = remainder * (pct / total_pct)
            broker.place_order(symbol, "buy", alloc_amt)
            log.info(f"Reinvested {alloc_amt} into {symbol}")
            log_event("holdings_reinvest", user=user, details={
                "symbol": symbol, "amount": alloc_amt, "reason": "reinvest"
            })
            audit_log_event("holdings_reinvest", user=user, reference=symbol, details={"amount": alloc_amt, "reason": "reinvest"})

    # === Step 4: Float excess auto-invest logic ===
    float_target_value = account_value * (float_pct / 100)
    float_excess = current_cash - float_target_value
    if float_excess > 1:
        prices = {symbol: broker.get_price(symbol) for symbol in etf_targets}
        total_pct = sum(etf_targets.values())
        for symbol, pct in etf_targets.items():
            alloc_amt = float_excess * (pct / total_pct)
            broker.place_order(symbol, "buy", alloc_amt)
            log.info(f"Invested float excess: {alloc_amt} into {symbol}")
            log_event("holdings_float_excess_invest", user=user, details={
                "symbol": symbol, "amount": alloc_amt, "reason": "float_excess"
            })
            audit_log_event("holdings_float_excess_invest", user=user, reference=symbol, details={"amount": alloc_amt, "reason": "float_excess"})

def perform_rebalance_cycle(user: str = "holdings_manager"):
    if not _is_bot_initialized():
        log.warning("Rebalance cycle: Bot not initialized/provisioned/bootstrapped.")
        return
    if not _is_broker_configured():
        log.warning("Rebalance cycle: No broker is configured or provisioned yet.")
        return

    broker = get_active_broker()
    holdings_cfg = load_holdings_secrets()
    etf_cfg = holdings_cfg.get("HOLDINGS_ETF_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)

    account_value = broker.get_account_value()
    holdings = broker.get_etf_holdings()

    if not _compliance_preview_or_abort(holdings, etf_targets, account_value):
        log.warning("Rebalance compliance preview failed, aborting rebalance.")
        return

    orders = compute_rebalance_orders(holdings, etf_targets, account_value)
    for order in orders:
        broker.place_order(order['symbol'], order['action'], order['amount'])
        log.info(f"Rebalance: {order['action']} ${order['amount']} of {order['symbol']}")
        log_event("holdings_rebalance", user=user, details=order)
        audit_log_event("holdings_rebalance", user=user, reference=order['symbol'], details=order)

def manual_holdings_action(action, user="manual"):
    if action == "rebalance":
        perform_rebalance_cycle(user)
        return {"result": "rebalance triggered"}
    return {"error": "invalid action"}

def main():
    log.info("Holdings manager started as persistent service.")
    while True:
        try:
            perform_holdings_cycle()
        except Exception as e:
            log.error(f"Exception in holdings cycle: {e}")
            log_event("holdings_manager_error", user="holdings_manager", details={"error": str(e)})
            audit_log_event("holdings_manager_error", user="holdings_manager", reference=None, details={"error": str(e)})
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
