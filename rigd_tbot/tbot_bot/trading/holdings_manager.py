# tbot_bot/trading/holdings_manager.py
 # Core logic for ETF purchases, sales, rebalancing, cash top-up, tax and payroll allocations.


from tbot_bot.trading.holdings_utils import (
    parse_etf_allocations,
    compute_cash_deficit,
    compute_realized_tax_cut,
    compute_post_tax_payroll_cut,
    compute_rebalance_orders,
)
from tbot_bot.support.utils_log import get_logger
from tbot_bot.config.env_bot import load_env_var

log = get_logger(__name__)

# Placeholder: replace with actual broker API interface
class BrokerInterface:
    def get_account_value(self): ...
    def get_cash_balance(self): ...
    def get_etf_holdings(self): ...
    def place_order(self, symbol, side, amount): ...
    def get_price(self, symbol): ...

def run_holdings_maintenance(broker: BrokerInterface, realized_gains: float):
    account_value = broker.get_account_value()
    current_cash = broker.get_cash_balance()

    float_pct = float(load_env_var("HOLDINGS_FLOAT_TARGET_PCT", 10))
    tax_pct = float(load_env_var("HOLDINGS_TAX_RESERVE_PCT", 20))
    payroll_pct = float(load_env_var("HOLDINGS_PAYROLL_PCT", 10))
    etf_cfg = load_env_var("HOLDINGS_ETF_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)

    # === Step 1: Top-up float ===
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
            if deficit <= 1: break

    # === Step 2: Allocate tax + payroll ===
    tax_cut = compute_realized_tax_cut(realized_gains, tax_pct)
    payroll_cut = compute_post_tax_payroll_cut(realized_gains, tax_cut, payroll_pct)
    log.info(f"Tax Reserve: {tax_cut}, Payroll: {payroll_cut}")
    # Placeholder: Transfer cash to reserve accounts if supported

    # === Step 3: Reinvest remainder ===
    remainder = realized_gains - tax_cut - payroll_cut
    if remainder > 1:
        prices = {symbol: broker.get_price(symbol) for symbol in etf_targets}
        total_pct = sum(etf_targets.values())
        for symbol, pct in etf_targets.items():
            alloc_amt = remainder * (pct / total_pct)
            broker.place_order(symbol, "buy", alloc_amt)
            log.info(f"Reinvested {alloc_amt} into {symbol}")

def run_rebalance_cycle(broker: BrokerInterface):
    account_value = broker.get_account_value()
    holdings = broker.get_etf_holdings()
    etf_cfg = load_env_var("HOLDINGS_ETF_LIST", "SCHD:50,SCHY:50")
    etf_targets = parse_etf_allocations(etf_cfg)

    orders = compute_rebalance_orders(holdings, etf_targets, account_value)
    for order in orders:
        broker.place_order(order['symbol'], order['action'], order['amount'])
        log.info(f"Rebalance: {order['action']} ${order['amount']} of {order['symbol']}")
