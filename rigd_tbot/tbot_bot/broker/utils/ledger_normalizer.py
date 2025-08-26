# tbot_bot/broker/utils/ledger_normalizer.py

from tbot_bot.support.utils_identity import get_bot_identity
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS

raw_id = get_bot_identity()
if isinstance(raw_id, str):
    parts = raw_id.split("_")
    BOT_IDENTITY = {
        "ENTITY_CODE": parts[0] if len(parts) > 0 else "UNKNOWN",
        "JURISDICTION_CODE": parts[1] if len(parts) > 1 else "UNKNOWN",
        "BROKER_CODE": parts[2] if len(parts) > 2 else "UNKNOWN",
        "BOT_ID": parts[3] if len(parts) > 3 else "UNKNOWN"
    }
elif isinstance(raw_id, dict):
    BOT_IDENTITY = raw_id
else:
    BOT_IDENTITY = {
        "ENTITY_CODE": "UNKNOWN",
        "JURISDICTION_CODE": "UNKNOWN",
        "BROKER_CODE": "UNKNOWN",
        "BOT_ID": "UNKNOWN"
    }

# Map raw broker actions to canonical ledger actions
ACTION_MAP = {
    "buy": "long",
    "sell": "short",
    "long": "long",
    "short": "short",
    "put": "put",
    "call": "call",
    "assignment": "assignment",
    "exercise": "exercise",
    "expire": "expire",
    "reorg": "reorg",
    "purchase": "long",
    "exit": "short",
    "close": "short",
    "open": "long",
    "fill": None,
    "partial_fill": None,
}

ALLOWED_ACTIONS = (
    "long", "short", "put", "inverse", "call", "assignment", "exercise", "expire", "reorg", "other"
)

def normalize_trade(trade, credential_hash=None):
    if not isinstance(trade, dict):
        return {k: None for k in TRADES_FIELDS}

    raw_action = trade.get("action") or trade.get("side") or None
    canonical_action = None
    side_value = None
    action_invalid = False
    unmapped_action = None

    if raw_action:
        raw_action_lower = str(raw_action).lower()
        canonical_action = ACTION_MAP.get(raw_action_lower, raw_action_lower)
        if canonical_action is None or canonical_action not in ALLOWED_ACTIONS:
            unmapped_action = canonical_action if canonical_action else raw_action_lower
            action_invalid = True
            canonical_action = None
        if raw_action_lower in ("debit", "credit"):
            side_value = raw_action_lower
        else:
            side_value = None
    else:
        raw_action_lower = None
        action_invalid = True
        canonical_action = None

    # Drop unmappable or None actions: enforce skip_insert
    if action_invalid or not canonical_action:
        mapping = {k: None for k in TRADES_FIELDS}
        mapping["skip_insert"] = True
        mapping["json_metadata"] = {
            "raw_broker": trade,
            "api_hash": credential_hash or "n/a",
            "unmapped_action": unmapped_action or raw_action or "missing"
        }
        mapping["trade_id"] = trade.get("id") or trade.get("trade_id") or trade.get("order_id")
        return mapping

    mapping = {
        "trade_id": trade.get("id") or trade.get("trade_id") or trade.get("order_id"),
        "symbol": trade.get("symbol") or trade.get("underlying"),
        "side": side_value,
        "action": canonical_action,
        "quantity": float(trade.get("qty") or trade.get("quantity") or trade.get("filled_qty") or 0),
        "quantity_type": trade.get("quantity_type"),
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
        "currency_code": trade.get("currency_code") or trade.get("currency", "USD"),
        "language_code": trade.get("language_code", "en"),
        "price_currency": trade.get("price_currency"),
        "fx_rate": trade.get("fx_rate"),
        "commission_currency": trade.get("commission_currency"),
        "fee_currency": trade.get("fee_currency"),
        "accrued_interest": float(trade.get("accrued_interest", 0.0)),
        "accrued_interest_currency": trade.get("accrued_interest_currency"),
        "tax": float(trade.get("tax", 0.0)),
        "tax_currency": trade.get("tax_currency"),
        "net_amount": trade.get("net_amount"),
        "settlement_date": trade.get("settlement_date"),
        "trade_date": trade.get("trade_date"),
        "description": trade.get("description"),
        "counterparty": trade.get("counterparty"),
        "sub_account": trade.get("sub_account"),
        "broker_code": trade.get("broker_code") or trade.get("broker", "ALPACA"),
        "entity_code": BOT_IDENTITY.get("ENTITY_CODE", "UNKNOWN"),
        "jurisdiction_code": BOT_IDENTITY.get("JURISDICTION_CODE", "UNKNOWN"),
        "bot_id": BOT_IDENTITY.get("BOT_ID", "UNKNOWN"),
        "json_metadata": {
            "raw_broker": trade,
            "api_hash": credential_hash or "n/a",
            "unmapped_action": None
        },
    }

    mapping["total_value"] = round(mapping["quantity"] * mapping["price"], 6)

    for k in TRADES_FIELDS:
        if k not in mapping:
            mapping[k] = None

    mapping["skip_insert"] = False

    return mapping
