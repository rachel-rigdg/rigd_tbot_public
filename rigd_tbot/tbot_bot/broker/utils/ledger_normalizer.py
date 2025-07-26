# tbot_bot/broker/utils/ledger_normalizer.py

def normalize_trade(trade, credential_hash=None):
    # This function must be robust to dicts from any broker and normalize fields.
    if not isinstance(trade, dict):
        return trade

    mapping = {
        "trade_id": trade.get("id") or trade.get("trade_id") or trade.get("order_id"),
        "symbol": trade.get("symbol") or trade.get("underlying"),
        "action": trade.get("side") or trade.get("action"),
        "quantity": float(trade.get("qty") or trade.get("quantity") or trade.get("filled_qty") or 0),
        "price": float(trade.get("price") or trade.get("filled_avg_price") or trade.get("fill_price") or 0),
        "fee": float(trade.get("fee", 0)),
        "commission": float(trade.get("commission", 0)),
        "datetime_utc": trade.get("filled_at") or trade.get("execution_time") or trade.get("date") or trade.get("datetime_utc"),
        "status": trade.get("status", ""),
        "total_value": 0,
        "json_metadata": {
            "raw_broker": trade,
            "api_hash": credential_hash or "n/a"
        }
    }
    mapping["total_value"] = mapping["quantity"] * mapping["price"]
    return mapping
