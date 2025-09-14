# tbot_bot/support/utils_identity.py
# Handles bot identity string and related metadata
import re

# Prefer the canonical validators from path_resolver (single source of truth)
try:
    from tbot_bot.support.path_resolver import (
        get_bot_identity_string_regex as _resolver_identity_regex_fn,
        validate_bot_identity as _resolver_validate_fn,
    )
    _IDENTITY_REGEX = _resolver_identity_regex_fn()
    _validate_identity = _resolver_validate_fn
except Exception:
    # Fallback (must match path_resolver.IDENTITY_PATTERN)
    _IDENTITY_REGEX = re.compile(r"^[A-Z]{2,6}_[A-Z]{2,4}_[A-Z]{2,10}_[A-Z0-9]{2,6}$")

    def _validate_identity(identity: str) -> None:
        if not identity or not _IDENTITY_REGEX.match(identity):
            raise ValueError(f"[utils_identity] Invalid BOT_IDENTITY_STRING: {identity!r}")

def is_identity_valid(identity: str) -> bool:
    """Return True if identity matches the canonical BOT_IDENTITY pattern."""
    return bool(identity and _IDENTITY_REGEX.match(identity))

def get_identity_parts(identity: str):
    """
    Split a valid identity into {entity, jurisdiction, broker, bot_id}.
    Returns None if invalid.
    """
    if not is_identity_valid(identity):
        return None
    entity, jurisdiction, broker, bot_id = identity.split("_", 3)
    return {
        "entity": entity,
        "jurisdiction": jurisdiction,
        "broker": broker,
        "bot_id": bot_id,
    }

def get_bot_identity_string():
    """
    Returns BOT_IDENTITY_STRING, loading it from secrets if needed.
    Returns "UNKNOWN_BOT" if not yet configured, in bootstrap mode, or invalid.
    """
    try:
        from tbot_bot.support.decrypt_secrets import load_bot_identity
        try:
            from tbot_bot.support.bootstrap_utils import is_first_bootstrap
            if is_first_bootstrap():
                return "UNKNOWN_BOT"
        except Exception:
            # If bootstrap utility missing or errors, continue to load identity.
            pass
        identity = load_bot_identity()
        if not identity or not is_identity_valid(identity):
            return "UNKNOWN_BOT"
        return identity
    except Exception:
        return "UNKNOWN_BOT"

def require_valid_identity() -> str:
    """
    Return a valid BOT_IDENTITY_STRING or raise ValueError using the canonical validator.
    Use this in callers that must fail-fast instead of silently falling back.
    """
    ident = get_bot_identity_string()
    _validate_identity(ident)  # raises if invalid
    return ident

def get_bot_identity():
    """
    Alias for get_bot_identity_string, for compatibility.
    """
    return get_bot_identity_string()
