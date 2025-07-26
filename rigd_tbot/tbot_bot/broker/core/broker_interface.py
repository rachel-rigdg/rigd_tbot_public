# tbot_bot/broker/core/broker_interface.py
# BrokerInterface: Defines the normalized, enforced interface for all adapters

class BrokerInterface:
    def __init__(self, env):
        pass

    def get_account_info(self):
        raise NotImplementedError

    def get_account_value(self):
        raise NotImplementedError

    def get_cash_balance(self):
        raise NotImplementedError

    def get_positions(self):
        raise NotImplementedError

    def get_position(self, symbol):
        raise NotImplementedError

    def submit_order(self, order):
        raise NotImplementedError

    def cancel_order(self, order_id):
        raise NotImplementedError

    def close_position(self, symbol):
        raise NotImplementedError

    def is_market_open(self):
        raise NotImplementedError

    def self_check(self):
        raise NotImplementedError

    def is_symbol_tradable(self, symbol):
        raise NotImplementedError

    def supports_fractional(self, symbol):
        raise NotImplementedError

    def get_min_order_size(self, symbol):
        raise NotImplementedError

    def get_price(self, symbol):
        raise NotImplementedError

    def get_etf_holdings(self):
        raise NotImplementedError

    def fetch_all_trades(self, start_date, end_date=None):
        raise NotImplementedError

    def fetch_cash_activity(self, start_date, end_date=None):
        raise NotImplementedError
