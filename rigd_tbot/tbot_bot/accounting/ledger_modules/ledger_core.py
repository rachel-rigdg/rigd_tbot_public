# tbot_bot/accounting/ledger_modules/ledger_core.py

"""
Core ledger DB logic and orchestrators.
Handles generic ledger database path/identity logic and high-level coordination used by other helpers.
No transactional, mapping, or account logic is implemented here.
"""

from tbot_bot.support.path_resolver import resolve_ledger_db_path
from tbot_bot.support.decrypt_secrets import load_bot_identity

def get_identity_tuple():
    """
    Returns (entity_code, jurisdiction_code, broker_code, bot_id) tuple from the decrypted bot identity string.
    """
    identity = load_bot_identity()
    return tuple(identity.split("_"))

def get_ledger_db_path():
    """
    Returns resolved ledger database path for the current bot identity.
    """
    entity_code, jurisdiction_code, broker_code, bot_id = get_identity_tuple()
    return resolve_ledger_db_path(entity_code, jurisdiction_code, broker_code, bot_id)
