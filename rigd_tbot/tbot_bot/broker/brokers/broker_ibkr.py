# tbot_bot/broker/brokers/ibkr.py
# Interactive Brokers implementation (single-broker only)

from ib_insync import IB, Stock, MarketOrder
from tbot_bot.trading.logs_bot import log_event

class IBKRBroker:
    def __init__(self, env):
        """
        Initializes IBKR broker using values from broker-agnostic env_bot.
        Expects TWS or IB Gateway running with API enabled.
        """
        self.host = env.get("BROKER_HOST", "127.0.0.1")
        self.port = int(env.get("BROKER_PORT", 7497))
        self.client_id = int(env.get("BROKER_CLIENT_ID", 1))
        self.username = env.get("BROKER_USERNAME")
        self.password = env.get("BROKER_PASSWORD")
        self.account_number = env.get("BROKER_ACCOUNT_NUMBER")
        self.api_key = env.get("BROKER_API_KEY")
        self.secret_key = env.get("BROKER_SECRET_KEY")
        self.url = env.get("BROKER_URL")

        self.client = IB()
        try:
            self.client.connect(self.host, self.port, clientId=self.client_id)
            self.connected = self.client.isConnected()
        except Exception as e:
            log_event("broker_ibkr", f"Connection failed: {e}")
            self.connected = False

    def self_check(self) -> bool:
        return self.connected

    def get_account_info(self):
        try:
            return self.client.accountSummary().df.to_dict()
        except Exception as e:
            log_event("broker_ibkr", f"Account info error: {e}")
            return {"error": str(e)}

    def get_positions(self):
        try:
            return self.client.positions()
        except Exception as e:
            log_event("broker_ibkr", f"Get positions failed: {e}")
            return []

    def get_position(self, symbol):
        try:
            return next((p for p in self.client.positions() if p.contract.symbol == symbol), None)
        except:
            return None

    def submit_order(self, order):
        """
        Submits a market order. Expects unified order dict:
        - symbol, qty, side, strategy
        """
        if not self.connected:
            return {"error": "IBKR not connected"}

        contract = Stock(order["symbol"], "SMART", "USD")
        action = "BUY" if order["side"].lower() == "buy" else "SELL"
        ib_order = MarketOrder(action, order["qty"])

        try:
            trade = self.client.placeOrder(contract, ib_order)
            return {
                "status": "submitted",
                "symbol": order["symbol"],
                "qty": order["qty"],
                "side": action,
                "order_id": trade.order.permId
            }
        except Exception as e:
            log_event("broker_ibkr", f"Submit order failed: {e}")
            return {"error": str(e)}

    def close_position(self, symbol):
        try:
            pos = self.get_position(symbol)
            if not pos:
                return {"message": f"No position to close for {symbol}"}
            action = "SELL" if pos.position > 0 else "BUY"
            order = MarketOrder(action, abs(pos.position))
            self.client.placeOrder(pos.contract, order)
            return {"status": "close submitted", "symbol": symbol}
        except Exception as e:
            log_event("broker_ibkr", f"Close position failed: {e}")
            return {"error": str(e)}

    def cancel_order(self, order_id):
        try:
            self.client.cancelOrder(order_id)
            return {"status": f"Order {order_id} cancelled"}
        except Exception as e:
            log_event("broker_ibkr", f"Cancel order error: {e}")
            return {"error": str(e)}

    def is_market_open(self):
        # Placeholder: IBKR has no direct market open call
        return True
