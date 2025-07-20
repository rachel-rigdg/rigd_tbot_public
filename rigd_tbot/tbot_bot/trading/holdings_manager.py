# tbot_bot/trading/holdings_manager.py
# Core logic for ETF purchases, sales, rebalancing, cash top-up, tax and payroll allocations
# loads all config from encrypted holdings secrets file, uses atomic writes and audit
# Broker selection is fully dynamic using get_broker_adapter() from broker_api.py
# NEVER loads or executes unless provisioning/bootstrapping are complete

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import time

from tbot_bot.trading.holdings_utils import (
    parse_etf_allocations,
    compute_cash_deficit,
    compute_realized_tax_cut,
    compute_post_tax_payroll_cut,
    compute_rebalance_orders,
)
from tbot_bot.support.holdings_secrets import load_holdings_secrets, save_holdings_secrets
from tbot_bot.support.utils_log import get_logger, log_event
from tbot_bot.broker.broker_api import get_broker_adapter
from tbot_bot.support.path_resolver import resolve_bot_state_path
from tbot_bot.support.bootstrap_utils import is_first_bootstrap

log = get_logger(__name__)

def _is_bot_initialized():
    """Return True only if bot is past config, provisioning, and bootstrapping."""
    if is_first_bootstrap(quiet_mode=True):
        return False
    state_path = resolve_bot_state_path()
    try:
        state = state_path.read_text(encoding="utf-8").strip()
        return state not in ("initialize", "provisioning", "bootstrapping")
    except Exception:
        return False

def _is_broker_configured():
    # Defensive check: Only proceed if a broker is actually configured and provisioned
    try:
        broker = get_broker_adapter()
        _ = broker.get_account_value()
        return True
    except Exception as e:
        log.warning(f"Broker not configured or not provisioned: {e}")
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
    holdings_cfg["NEXT_REBALANCE_DUE"] = next_due.isoformat()
    save_holdings_secrets(holdings_cfg)

def run_holdings_maintenance(realized_gains: float = 0.0, user: str = "system"):
    if not _is_bot_initialized():
        log.warning("Holdings maintenance blocked: Bot not initialized/provisioned/bootstrapped.")
        return
    if not _is_broker_configured():
        log.warning("Holdings maintenance aborted: No broker is configured or provisioned yet.")
        return

    broker = get_broker_adapter()
    holdings_cfg = load_holdings_secrets()
    float_pct = float(holdings_cfg.get("FLOAT_TARGET_PCT", 10))
    tax_pct = float(holdings_cfg.get("TAX_RESERVE_PCT", 20))
    payroll_pct = float(holdings_cfg.get("PAYROLL_PCT", 10))
    etf_cfg = holdings_cfg.get("ETF_ALLOC_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)

    account_value = broker.get_account_value()
    current_cash = broker.get_cash_balance()

    # === Step 0: Conditional rebalance if due ===
    if _should_rebalance(holdings_cfg):
        run_rebalance_cycle(user)
        _mark_rebalance_complete(holdings_cfg)

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
    if not _is_bot_initialized():
        log.warning("Rebalance cycle blocked: Bot not initialized/provisioned/bootstrapped.")
        return
    if not _is_broker_configured():
        log.warning("Rebalance cycle aborted: No broker is configured or provisioned yet.")
        return

    broker = get_broker_adapter()
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

"""
==============================================================================
MODULE ARCHITECTURE:
- All top-up, rebalancing, reserve, and allocation logic is encapsulated here.
- Supervisor/process manager only triggers run_holdings_maintenance(); *all*
  logic about "should I run X now" is inside this module.
- This ensures audit safety, future-proofing, and no external double-booking.
==============================================================================
"""
