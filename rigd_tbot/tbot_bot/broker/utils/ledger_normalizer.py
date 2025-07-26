# tbot_bot/broker/utils/ledger_normalizer.py

from tbot_bot.support.utils_identity import get_bot_identity

BOT_IDENTITY = get_bot_identity()

def normalize_trade(trade, credential_hash=None):
    # This function must be robust to dicts from any broker and normalize fields.
    if not isinstance(trade, dict):
        return trade

    mapping = {
        "trade_id": trade.get("id") or trade.get("trade_id") or trade.get("order_id"),
        "symbol": trade.get("symbol") or trade.get("underlying"),
        "side": trade.get("side") or trade.get("action"),
        "quantity": float(trade.get("qty") or trade.get("quantity") or trade.get("filled_qty") or 0),
        "price": float(trade.get("price") or trade.get("filled_avg_price") or trade.get("fill_price") or 0),
        "fee": float(trade.get("fee", 0)),
        "commission": float(trade.get("commission", 0)),
        "datetime_utc": (
            trade.get("transaction_time") or
            trade.get("filled_at") or
            trade.get("execution_time") or
            trade.get("date") or
            trade.get("datetime_utc")
        ),
        "status": trade.get("status", trade.get("order_status", "")),
        "strategy": trade.get("strategy", "UNKNOWN"),
        "account": trade.get("account", "default"),
        "currency_code": trade.get("currency", "USD"),
        "broker_code": trade.get("broker", "ALPACA"),
        "entity_code": BOT_IDENTITY.get("ENTITY_CODE", "UNKNOWN"),
        "jurisdiction_code": BOT_IDENTITY.get("JURISDICTION_CODE", "UNKNOWN"),
        "BOT_ID": BOT_IDENTITY.get("BOT_ID", "UNKNOWN"),
        "json_metadata": {
            "raw_broker": trade,
            "api_hash": credential_hash or "n/a"
        }
    }

    mapping["total_value"] = round(mapping["quantity"] * mapping["price"], 6)
    return mapping
