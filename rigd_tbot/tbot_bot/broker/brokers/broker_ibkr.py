# tbot_bot/broker/brokers/ibkr.py
# Interactive Brokers implementation (single-broker only)

from ib_insync import IB, Stock, MarketOrder
from tbot_bot.support.utils_log import log_event
import csv
import io
import hashlib
from datetime import datetime

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
        self.credential_hash = hashlib.sha256((str(self.username) + str(self.api_key)).encode("utf-8")).hexdigest()
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
                    unique[t.order.permId] = t
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

    # ============== BROKER SYNC INTERFACE (SPEC) ==============

    def fetch_all_trades(self, start_date, end_date=None):
        """
        Returns all filled trades in OFX/ledger-normalized dicts.
        Aggregates partial fills by permId, ensures required field normalization and logs credential use.
        """
        trades = []
        try:
            all_trades = self.client.trades()
            trade_map = {}
            for t in all_trades:
                if t.orderStatus.status not in ["Filled", "filled"]:
                    continue
                trade_id = str(t.order.permId)
                trade_hash = hashlib.sha256(str(vars(t)).encode("utf-8")).hexdigest()
                trade_time = (
                    str(t.log[-1].time) if t.log and t.log[-1].time else None
                )
                if start_date and trade_time and trade_time < start_date:
                    continue
                if end_date and trade_time and trade_time > end_date:
                    continue
                filled_qty = float(t.order.totalQuantity)
                avg_price = float(t.orderStatus.avgFillPrice or 0)
                fee = 0
                commission = 0
                if trade_id not in trade_map:
                    trade_map[trade_id] = {
                        "trade_id": trade_id,
                        "symbol": t.contract.symbol,
                        "action": t.order.action,
                        "quantity": filled_qty,
                        "price": avg_price,
                        "fee": fee,
                        "fee": commission,
                        "datetime_utc": trade_time,
                        "status": t.orderStatus.status,
                        "total_value": filled_qty * avg_price,
                        "json_metadata": {
                            "raw_broker": str(vars(t)),
                            "api_hash": trade_hash,
                            "credential_hash": self.credential_hash
                        }
                    }
                else:
                    prev = trade_map[trade_id]
                    prev["quantity"] += filled_qty
                    prev["total_value"] += filled_qty * avg_price
                    prev["fee"] += fee
                    prev["fee"] += commission
            trades = list(trade_map.values())
            log_event("broker_ibkr", f"fetch_all_trades complete, {len(trades)} trades. cred_hash={self.credential_hash}", level="info")
            return trades
        except Exception as e:
            log_event("broker_ibkr", f"fetch_all_trades error: {e}", level="error")
            return []

    def fetch_cash_activity(self, start_date, end_date=None):
        """
        Returns all cash/dividend/fee activity in OFX/ledger-normalized dicts.
        Handles available account summary as cash events, normalization, and audit.
        """
        activities = []
        try:
            account_summ = self.client.accountSummary()
            # IBKR API: use available data, not full fidelity vs. Alpaca; record basic cash activity
            activity_id = f"acct_activity_{datetime.utcnow().isoformat()}"
            for c in account_summ:
                activities.append({
                    "trade_id": activity_id,
                    "symbol": None,
                    "action": c.tag,
                    "quantity": float(c.value or 0),
                    "price": 0,
                    "fee": 0,
                    "fee": 0,
                    "datetime_utc": str(datetime.utcnow()),
                    "status": "ok",
                    "total_value": float(c.value or 0),
                    "json_metadata": {
                        "raw_broker": str(vars(c)),
                        "api_hash": hashlib.sha256(str(vars(c)).encode("utf-8")).hexdigest(),
                        "credential_hash": self.credential_hash
                    }
                })
            log_event("broker_ibkr", f"fetch_cash_activity complete, {len(activities)} entries. cred_hash={self.credential_hash}", level="info")
            return activities
        except Exception as e:
            log_event("broker_ibkr", f"fetch_cash_activity error: {e}", level="error")
            return []

    # ============ EXTENDED RAW DATA DUMP (NEW) ============

    def fetch_all_trades_raw(self, start_date=None, end_date=None):
        """
        Fetches and returns ALL raw trades (ib_insync Trade objects) within date range, paginated if available.
        """
        try:
            all_trades = self.client.trades()
            raw = []
            for t in all_trades:
                trade_time = str(t.log[-1].time) if t.log and t.log[-1].time else None
                if start_date and trade_time and trade_time < start_date:
                    continue
                if end_date and trade_time and trade_time > end_date:
                    continue
                raw.append(vars(t))
            log_event("broker_ibkr", f"fetch_all_trades_raw complete, {len(raw)} entries. cred_hash={self.credential_hash}", level="info")
            return raw
        except Exception as e:
            log_event("broker_ibkr", f"fetch_all_trades_raw error: {e}", level="error")
            return []

    def fetch_all_account_summary_raw(self):
        """
        Returns the full raw account summary as provided by IBKR API (ib_insync TagValue objects).
        """
        try:
            account_summ = self.client.accountSummary()
            raw = [vars(c) for c in account_summ]
            log_event("broker_ibkr", f"fetch_all_account_summary_raw complete, {len(raw)} entries. cred_hash={self.credential_hash}", level="info")
            return raw
        except Exception as e:
            log_event("broker_ibkr", f"fetch_all_account_summary_raw error: {e}", level="error")
            return []

    def fetch_all_orders_raw(self, start_date=None, end_date=None):
        """
        Fetches and returns ALL raw open/closed orders (ib_insync Order objects) within date range.
        """
        try:
            all_orders = self.client.orders()
            raw = []
            for o in all_orders:
                order_time = str(o.transmitTime) if hasattr(o, "transmitTime") and o.transmitTime else None
                if start_date and order_time and order_time < start_date:
                    continue
                if end_date and order_time and order_time > end_date:
                    continue
                raw.append(vars(o))
            log_event("broker_ibkr", f"fetch_all_orders_raw complete, {len(raw)} entries. cred_hash={self.credential_hash}", level="info")
            return raw
        except Exception as e:
            log_event("broker_ibkr", f"fetch_all_orders_raw error: {e}", level="error")
            return []

    def fetch_all_executions_raw(self, start_date=None, end_date=None):
        """
        Fetches all executions (fills) with full raw execution detail, filtered by date if provided.
        """
        try:
            executions = self.client.executions()
            raw = []
            for exec_report in executions:
                exec_time = str(exec_report.time) if hasattr(exec_report, "time") else None
                if start_date and exec_time and exec_time < start_date:
                    continue
                if end_date and exec_time and exec_time > end_date:
                    continue
                raw.append(vars(exec_report))
            log_event("broker_ibkr", f"fetch_all_executions_raw complete, {len(raw)} entries. cred_hash={self.credential_hash}", level="info")
            return raw
        except Exception as e:
            log_event("broker_ibkr", f"fetch_all_executions_raw error: {e}", level="error")
            return []

    def fetch_all_portfolio_raw(self):
        """
        Fetches and returns ALL raw portfolio positions as provided by IBKR API.
        """
        try:
            portfolio = self.client.portfolio()
            raw = [vars(p) for p in portfolio]
            log_event("broker_ibkr", f"fetch_all_portfolio_raw complete, {len(raw)} entries. cred_hash={self.credential_hash}", level="info")
            return raw
        except Exception as e:
            log_event("broker_ibkr", f"fetch_all_portfolio_raw error: {e}", level="error")
            return []
