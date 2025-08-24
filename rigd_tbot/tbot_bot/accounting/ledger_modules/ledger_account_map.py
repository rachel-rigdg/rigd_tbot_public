# tbot_bot/accounting/ledger_modules/ledger_account_map.py
# Thin wrapper over versioned COA mapping (no static dicts).
# Provides cached, entity/jurisdiction/broker-aware lookups and strict failures on unmapped codes.

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, Optional, Tuple

from tbot_bot.accounting.coa_mapping_table import (
    get_version as _get_version,
    get_accounts_for as _get_accounts_for,
    get_mapping_for_transaction as _get_mapping_for_transaction,
)
from tbot_bot.support.utils_identity import get_bot_identity


def _identity_tuple(
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    if entity_code and jurisdiction_code and broker_code and bot_id:
        return entity_code, jurisdiction_code, broker_code, bot_id
    parts = str(get_bot_identity()).split("_")
    if len(parts) >= 4:
        return parts[0], parts[1], parts[2], parts[3]
    raise ValueError("Invalid BOT identity; expected 'ENTITY_JURISDICTION_BROKER_BOTID'")


@lru_cache(maxsize=128)
def _cached_version(
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
) -> int:
    ec, jc, bc, bid = _identity_tuple(entity_code, jurisdiction_code, broker_code, bot_id)
    return int(_get_version(ec, jc, bc, bid))


def _resolve_version(version_id: Optional[int], entity_code: Optional[str], jurisdiction_code: Optional[str],
                     broker_code: Optional[str], bot_id: Optional[str]) -> int:
    if version_id is not None:
        return int(version_id)
    return _cached_version(entity_code, jurisdiction_code, broker_code, bot_id)


def get_account_path(
    code: str,
    *,
    side: str = "debit",
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
    version_id: Optional[int] = None,
) -> str:
    """
    Resolve an account path for a logical code via the versioned COA mapping.
    Prefers the debit side unless 'side="credit"' is specified.
    Strict: raises KeyError if unmapped.
    """
    ec, jc, bc, bid = _identity_tuple(entity_code, jurisdiction_code, broker_code, bot_id)
    ver = _resolve_version(version_id, ec, jc, bc, bid)
    accounts = _get_accounts_for(code, ec, jc, bc, bid, ver)
    if not accounts:
        raise KeyError(f"Unmapped COA code: {code} (entity={ec}, juris={jc}, broker={bc}, ver={ver})")
    debit, credit = accounts
    if side == "credit":
        return str(credit)
    return str(debit)


def map_transaction_to_accounts(
    txn: Dict[str, str],
    *,
    entity_code: Optional[str] = None,
    jurisdiction_code: Optional[str] = None,
    broker_code: Optional[str] = None,
    bot_id: Optional[str] = None,
    version_id: Optional[int] = None,
) -> Tuple[str, str, int]:
    """
    Map a broker transaction dict → (debit_account, credit_account, mapping_version_id).
    Strict: raises KeyError if unmapped.
    """
    ec, jc, bc, bid = _identity_tuple(entity_code, jurisdiction_code, broker_code, bot_id)
    ver = _resolve_version(version_id, ec, jc, bc, bid)
    row = _get_mapping_for_transaction(txn, ec, jc, bc, bid, ver)
    if not row:
        raise KeyError(f"Unmapped transaction for entity={ec}, juris={jc}, broker={bc}, ver={ver}: {txn}")
    return str(row.get("debit_account")), str(row.get("credit_account")), ver


def load_broker_code() -> str:
    """
    Broker code from BOT identity (env-only via utils_identity).
    """
    return _identity_tuple()[2]


def load_account_number() -> str:
    """
    Account number via environment (env-only).
    Looks up ACCOUNT_NUMBER or ACCOUNT_ID; returns '' if not set.
    """
    return os.getenv("ACCOUNT_NUMBER") or os.getenv("ACCOUNT_ID") or ""
