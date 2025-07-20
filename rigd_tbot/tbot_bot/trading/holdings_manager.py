# tbot_bot/trading/holdings_manager.py
# Core logic for ETF purchases, sales, rebalancing, cash top-up, tax and payroll allocations
#  loads all config from encrypted holdings secrets file, uses atomic writes and audit

from datetime import datetime
from dateutil.relativedelta import relativedelta

from tbot_bot.trading.holdings_utils import (
    parse_etf_allocations,
    compute_cash_deficit,
    compute_realized_tax_cut,
    compute_post_tax_payroll_cut,
    compute_rebalance_orders,
)
from tbot_bot.support.holdings_secrets import load_holdings_secrets, save_holdings_secrets
from tbot_bot.support.utils_log import get_logger, log_event
from tbot_bot.broker.broker_api import get_broker_adapter  # <<== Standardized live broker loader

log = get_logger(__name__)

def run_holdings_maintenance(realized_gains: float, user: str = "system"):
    broker = get_broker_adapter()
    holdings_cfg = load_holdings_secrets()
    float_pct = float(holdings_cfg.get("FLOAT_TARGET_PCT", 10))
    tax_pct = float(holdings_cfg.get("TAX_RESERVE_PCT", 20))
    payroll_pct = float(holdings_cfg.get("PAYROLL_PCT", 10))
    etf_cfg = holdings_cfg.get("ETF_ALLOC_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)

    # === Step 0: Conditional rebalance if NEXT_REBALANCE_DUE reached ===
    rebalance_interval = int(holdings_cfg.get("HOLDINGS_REBALANCE_INTERVAL", 3))
    next_rebalance_due = holdings_cfg.get("NEXT_REBALANCE_DUE")
    try:
        if next_rebalance_due:
            rebalance_due_date = datetime.fromisoformat(next_rebalance_due).date()
            if datetime.utcnow().date() >= rebalance_due_date:
                run_rebalance_cycle(user)
                next_due = datetime.utcnow().date() + relativedelta(months=rebalance_interval)
                holdings_cfg["NEXT_REBALANCE_DUE"] = next_due.isoformat()
                save_holdings_secrets(holdings_cfg)
    except Exception as e:
        log.warning(f"Rebalance date check failed: {e}")

    account_value = broker.get_account_value()
    current_cash = broker.get_cash_balance()

    # === Step 1: Top-up float (sell ETFs if needed) ===
    deficit = compute_cash_deficit(account_value, float_pct, current_cash)
    if deficit > 1:
        holdings = broker.get_etf_holdings()
        sorted_by_value = sorted(holdings.items(), key=lambda x: -x[1])
        for symbol, value in sorted_by_value:
            if value < 1: continue
            sell_amt = min(deficit, value)
            broker.place_order(symbol, "sell", sell_amt)
            deficit -= sell_amt
            log.info(f"Topped up cash by selling {sell_amt} of {symbol}")
            log_event("holdings_float_topup", user=user, details={
                "symbol": symbol, "amount": sell_amt, "reason": "float_topup"
            })
            if deficit <= 1: break

    # === Step 2: Allocate tax + payroll reserve ===
    tax_cut = compute_realized_tax_cut(realized_gains, tax_pct)
    payroll_cut = compute_post_tax_payroll_cut(realized_gains, tax_cut, payroll_pct)
    log.info(f"Tax Reserve: {tax_cut}, Payroll: {payroll_cut}")
    log_event("holdings_reserve_allocation", user=user, details={
        "tax_cut": tax_cut, "payroll_cut": payroll_cut
    })
    # Placeholder: Transfer cash to reserve accounts if supported

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

def run_rebalance_cycle(user: str = "system"):
    broker = get_broker_adapter()

    # === Load persistent holdings config from encrypted secrets ===
    holdings_cfg = load_holdings_secrets()
    etf_cfg = holdings_cfg.get("ETF_ALLOC_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)

    account_value = broker.get_account_value()
    holdings = broker.get_etf_holdings()

    orders = compute_rebalance_orders(holdings, etf_targets, account_value)
    for order in orders:
        broker.place_order(order['symbol'], order['action'], order['amount'])
        log.info(f"Rebalance: {order['action']} ${order['amount']} of {order['symbol']}")
        log_event("holdings_rebalance", user=user, details=order)

# All config changes and allocations must be persisted via support/holdings_secrets.py and not via .env_bot or any ad hoc source.
# All changes are atomically written, rotated, and audit logged via the above module.
