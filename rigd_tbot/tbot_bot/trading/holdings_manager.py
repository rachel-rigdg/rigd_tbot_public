# tbot_bot/trading/holdings_manager.py
# Persistent process for all holdings ops: float top-up, rebalance, tax/payroll allocation.
# Loads config from holdings_secrets, routes all trades via broker_api.
# Writes to audit log and ledger. No business logic lives in the supervisor.

import time
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
from tbot_bot.accounting.ledger_modules.ledger_compliance_filter import compliance_filter_ledger_entry
from datetime import datetime, timezone, timedelta

print(f"[LAUNCH] holdings_manager.py launched @ {datetime.now(timezone.utc).isoformat()}", flush=True)

log = get_logger(__name__)

def _warn_or_info(msg):
    if hasattr(log, "warn"):
        log.warn(msg)
    else:
        log.info(msg)

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
        _warn_or_info(f"Broker not configured or not provisioned: {e}")
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
        _warn_or_info(f"Rebalance date check failed: {e}")
    return False

def _mark_rebalance_complete(holdings_cfg):
    rebalance_interval = int(holdings_cfg.get("HOLDINGS_REBALANCE_INTERVAL", 3))
    next_due = datetime.utcnow().date() + relativedelta(months=rebalance_interval)
    save_holdings_secrets({**holdings_cfg, "NEXT_REBALANCE_DUE": next_due.isoformat()}, user="holdings_manager", reason="rebalance_complete")

def _compliance_preview_or_abort(holdings, etf_targets, account_value):
    compliance_ok, preview = simulate_rebalance_compliance(holdings, etf_targets, account_value)
    if not compliance_ok:
        _warn_or_info(f"Rebalance/compliance preview failed: {preview}")
        log_event("holdings_compliance_block", f"Compliance block: {preview}", level="warning", extra={"reason": preview})
        audit_log_event("holdings_compliance_block", user="holdings_manager", reference=None, details={"reason": preview})
        return False
    return True

def get_holdings_status():
    broker = get_active_broker()
    account_value = broker.get_account_value()
    cash = broker.get_cash_balance()
    holdings_cfg = load_holdings_secrets()
    etf_cfg = holdings_cfg.get("HOLDINGS_ETF_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)
    next_rebalance_due = holdings_cfg.get("NEXT_REBALANCE_DUE")
    etf_holdings = []
    live = {}
    try:
        broker_positions = broker.get_etf_positions()
        for etf in broker_positions:
            live[etf.get("symbol")] = etf
    except Exception as e:
        _warn_or_info(f"Failed to fetch ETF holdings: {e}")
    for symbol, alloc in etf_targets.items():
        etf_live = live.get(symbol, {})
        etf_holdings.append({
            "symbol": symbol,
            "allocation_pct": alloc,
            "purchase_price": etf_live.get("purchase_price", 0),
            "units": etf_live.get("units", 0),
            "market_price": etf_live.get("market_price", 0),
            "market_value": etf_live.get("market_value", 0),
            "unrealized_pl": etf_live.get("unrealized_pl", 0),
            "total_gain_loss": etf_live.get("total_gain_loss", 0)
        })
    return {
        "account_value": account_value,
        "cash": cash,
        "next_rebalance_due": next_rebalance_due,
        "etf_holdings": etf_holdings
    }

def perform_holdings_cycle(realized_gains: float = 0.0, user: str = "holdings_manager"):
    if not _is_bot_initialized():
        _warn_or_info("Holdings manager: Bot not initialized/provisioned/bootstrapped.")
        return
    if not _is_broker_configured():
        _warn_or_info("Holdings manager: No broker is configured or provisioned yet.")
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
            _warn_or_info("Rebalance blocked for compliance, not executed.")
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
            sell_order = {"symbol": symbol, "action": "sell", "amount": sell_amt}
            if compliance_filter_ledger_entry(sell_order):
                broker.place_order(symbol, "sell", sell_amt)
                deficit -= sell_amt
                _warn_or_info(f"Topped up cash by selling {sell_amt} of {symbol}")
                log_event("holdings_float_topup", f"Topped up cash by selling {sell_amt} of {symbol}", level="info", extra={
                    "symbol": symbol, "amount": sell_amt, "reason": "float_topup"
                })
                audit_log_event("holdings_float_topup", user=user, reference=symbol, details={"amount": sell_amt, "reason": "float_topup"})
            if deficit <= 1:
                break

    # === Step 2: Allocate tax + payroll reserve ===
    tax_cut = compute_realized_tax_cut(realized_gains, tax_pct)
    payroll_cut = compute_post_tax_payroll_cut(realized_gains, tax_cut, payroll_pct)
    _warn_or_info(f"Tax Reserve: {tax_cut}, Payroll: {payroll_cut}")
    log_event("holdings_reserve_allocation", f"Tax Reserve: {tax_cut}, Payroll: {payroll_cut}", level="info", extra={
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
            buy_order = {"symbol": symbol, "action": "buy", "amount": alloc_amt}
            if compliance_filter_ledger_entry(buy_order):
                broker.place_order(symbol, "buy", alloc_amt)
                _warn_or_info(f"Reinvested {alloc_amt} into {symbol}")
                log_event("holdings_reinvest", f"Reinvested {alloc_amt} into {symbol}", level="info", extra={
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
            float_order = {"symbol": symbol, "action": "buy", "amount": alloc_amt}
            if compliance_filter_ledger_entry(float_order):
                broker.place_order(symbol, "buy", alloc_amt)
                _warn_or_info(f"Invested float excess: {alloc_amt} into {symbol}")
                log_event("holdings_float_excess_invest", f"Invested float excess: {alloc_amt} into {symbol}", level="info", extra={
                    "symbol": symbol, "amount": alloc_amt, "reason": "float_excess"
                })
                audit_log_event("holdings_float_excess_invest", user=user, reference=symbol, details={"amount": alloc_amt, "reason": "float_excess"})

def perform_rebalance_cycle(user: str = "holdings_manager"):
    if not _is_bot_initialized():
        _warn_or_info("Rebalance cycle: Bot not initialized/provisioned/bootstrapped.")
        return
    if not _is_broker_configured():
        _warn_or_info("Rebalance cycle: No broker is configured or provisioned yet.")
        return

    broker = get_active_broker()
    holdings_cfg = load_holdings_secrets()
    etf_cfg = holdings_cfg.get("HOLDINGS_ETF_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)

    account_value = broker.get_account_value()
    holdings = broker.get_etf_holdings()

    if not _compliance_preview_or_abort(holdings, etf_targets, account_value):
        _warn_or_info("Rebalance compliance preview failed, aborting rebalance.")
        return

    orders = compute_rebalance_orders(holdings, etf_targets, account_value)
    for order in orders:
        if compliance_filter_ledger_entry(order):
            broker.place_order(order['symbol'], order['action'], order['amount'])
            _warn_or_info(f"Rebalance: {order['action']} ${order['amount']} of {order['symbol']}")
            log_event("holdings_rebalance", f"Rebalance: {order['action']} ${order['amount']} of {order['symbol']}", level="info", extra=order)
            audit_log_event("holdings_rebalance", user=user, reference=order['symbol'], details=order)

def manual_holdings_action(action, user="manual"):
    if action == "rebalance":
        perform_rebalance_cycle(user)
        return {"result": "rebalance triggered"}
    return {"error": "invalid action"}

def main():
    _warn_or_info("Holdings manager started as persistent service.")
    while True:
        try:
            perform_holdings_cycle()
        except Exception as e:
            _warn_or_info(f"Exception in holdings cycle: {e}")
            log_event("holdings_manager_error", f"Exception: {e}", level="error", extra={"error": str(e)})
            audit_log_event("holdings_manager_error", user="holdings_manager", reference=None, details={"error": str(e)})
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
