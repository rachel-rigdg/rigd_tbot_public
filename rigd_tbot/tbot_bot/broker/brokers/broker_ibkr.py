# tbot_bot/broker/brokers/ibkr.py
# Interactive Brokers implementation (single-broker only)

from ib_insync import IB, Stock, MarketOrder
from tbot_bot.support.utils_log import log_event  # FIXED: use correct logger
import csv
import io

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
        self.broker_token = env.get("BROKER_TOKEN", "")
        self.url = env.get("BROKER_URL")

        self.client = IB()
        try:
            self.client.connect(self.host, self.port, clientId=self.client_id)
            self.connected = self.client.isConnected()
        except Exception as e:
            log_event("broker_ibkr", f"Connection failed: {e}", level="error")
            self.connected = False

    def self_check(self) -> bool:
        return self.connected

    def get_account_info(self):
        try:
            return self.client.accountSummary().df.to_dict()
        except Exception as e:
            log_event("broker_ibkr", f"Account info error: {e}", level="error")
            return {"error": str(e)}

    def get_account_value(self):
        try:
            # Use "TotalCashValue" or "NetLiquidation" for account value
            summary = self.client.accountSummary().df
            if "NetLiquidation" in summary.index:
                return float(summary.loc["NetLiquidation"]["value"])
            elif "TotalCashValue" in summary.index:
                return float(summary.loc["TotalCashValue"]["value"])
            else:
                return 0.0
        except Exception as e:
            log_event("broker_ibkr", f"get_account_value error: {e}", level="error")
            return 0.0

    def get_cash_balance(self):
        try:
            summary = self.client.accountSummary().df
            if "TotalCashValue" in summary.index:
                return float(summary.loc["TotalCashValue"]["value"])
            return 0.0
        except Exception as e:
            log_event("broker_ibkr", f"get_cash_balance error: {e}", level="error")
            return 0.0

    def get_positions(self):
        try:
            return self.client.positions()
        except Exception as e:
            log_event("broker_ibkr", f"Get positions failed: {e}", level="error")
            return []

    def get_position(self, symbol):
        try:
            return next((p for p in self.client.positions() if p.contract.symbol == symbol), None)
        except Exception:
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
            log_event("broker_ibkr", f"Submit order failed: {e}", level="error")
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
            log_event("broker_ibkr", f"Close position failed: {e}", level="error")
            return {"error": str(e)}

    def cancel_order(self, order_id):
        try:
            self.client.cancelOrder(order_id)
            return {"status": f"Order {order_id} cancelled"}
        except Exception as e:
            log_event("broker_ibkr", f"Cancel order error: {e}", level="error")
            return {"error": str(e)}

    def is_market_open(self):
        # Placeholder: IBKR has no direct market open call
        return True

    def is_symbol_tradable(self, symbol):
        try:
            contract = Stock(symbol, "SMART", "USD")
            details = self.client.reqContractDetails(contract)
            return bool(details)
        except Exception:
            return False

    # ========== SPEC ENFORCEMENT BELOW ==========

    def supports_fractional(self, symbol):
        """
        Returns True if symbol is fractionable on IBKR.
        """
        try:
            contract = Stock(symbol, "SMART", "USD")
            details = self.client.reqContractDetails(contract)
            if not details:
                return False
            # Heuristic: IBKR US stocks supporting fractional trading
            for d in details:
                # minTick < 1.0 is not a reliable IBKR check, so fallback to IBKR "isFractional" attribute if present
                if hasattr(d, 'isFractional') and getattr(d, 'isFractional', False):
                    return True
                # fallback: allow for US stocks < 1 share
                if hasattr(d, "minSize") and d.minSize and d.minSize < 1.0:
                    return True
            return False
        except Exception:
            return False

    def get_min_order_size(self, symbol):
        """
        Returns the min order size (float) for symbol. Fallback to 1.0 if unavailable.
        """
        try:
            contract = Stock(symbol, "SMART", "USD")
            details = self.client.reqContractDetails(contract)
            if details and hasattr(details[0], "minSize") and details[0].minSize is not None:
                return float(details[0].minSize)
            return 1.0
        except Exception:
            return 1.0

    def download_trade_ledger_csv(self, start_date=None, end_date=None, output_path=None):
        """
        Downloads executed trades from IBKR and writes a deduplicated CSV to output_path.
        """
        try:
            trades = self.client.trades()
            unique = {}
            for t in trades:
                if t.order.permId:
                    unique[t.order.permId] = t  # dedupe by IBKR order permId
            fieldnames = [
                "perm_id", "symbol", "qty", "action", "filled", "avg_fill_price", "status", "filled_time"
            ]
            rows = []
            for t in unique.values():
                rows.append({
                    "perm_id": t.order.permId,
                    "symbol": t.contract.symbol,
                    "qty": t.order.totalQuantity,
                    "action": t.order.action,
                    "filled": t.filled,
                    "avg_fill_price": t.orderStatus.avgFillPrice,
                    "status": t.orderStatus.status,
                    "filled_time": str(t.log[-1].time) if t.log else ""
                })
            if output_path:
                with open(output_path, "w", newline="") as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
            else:
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
                return output.getvalue()
        except Exception as e:
            log_event("broker_ibkr", f"Download trade ledger failed: {e}", level="error")
            raise
