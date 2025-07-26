# tbot_bot/broker/core/base_broker.py

from abc import ABC, abstractmethod

class BaseBroker(ABC):
    """Abstract base for all brokers."""
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def get_account_info(self): pass

    @abstractmethod
    def get_positions(self): pass

    @abstractmethod
    def get_position(self, symbol): pass

    @abstractmethod
    def place_order(self, symbol=None, side=None, amount=None, order=None): pass

    @abstractmethod
    def cancel_order(self, order_id): pass

    @abstractmethod
    def close_position(self, symbol): pass

    @abstractmethod
    def is_symbol_tradable(self, symbol): pass

    @abstractmethod
    def supports_fractional(self, symbol): pass

    @abstractmethod
    def get_min_order_size(self, symbol): pass

    @abstractmethod
    def get_price(self, symbol): pass

    @abstractmethod
    def fetch_all_trades(self, start_date, end_date=None): pass

    @abstractmethod
    def fetch_cash_activity(self, start_date, end_date=None): pass

    @abstractmethod
    def self_check(self): pass
