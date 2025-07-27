# tbot_bot/accounting/ledger_utils.py
# Main import/exports only. All logic refactored to helpers in ledger/.
from .ledger_modules.ledger_db import *
from .ledger_modules.ledger_account_map import *
from .ledger_modules.ledger_entry import *
from .ledger_modules.ledger_balance import *
from .ledger_modules.ledger_double_entry import *
from .ledger_modules.ledger_audit import *
from .ledger_modules.ledger_snapshot import *
from .ledger_modules.ledger_misc import *
from .ledger_modules.ledger_fields import *
from .ledger_modules.ledger_grouping import *
from .ledger_modules.ledger_deduplication import *
from .ledger_modules.ledger_query import *

from tbot_bot.broker.utils.ledger_normalizer import normalize_trade
from tbot_bot.accounting.ledger_modules.ledger_fields import TRADES_FIELDS

def enforce_normalized_trade(trade):
    norm = normalize_trade(trade)
    if norm.get("skip_insert", False):
        return None
    return norm

def enforce_trades_normalized(trades):
    result = []
    for t in trades:
        n = enforce_normalized_trade(t)
        if n:
            result.append(n)
    return result
