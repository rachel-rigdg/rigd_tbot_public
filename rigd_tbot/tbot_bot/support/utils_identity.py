# tbot_bot/support/utils_identity.py
# Handles bot identity string and related metadata

def get_bot_identity_string():
    """
    Returns BOT_IDENTITY_STRING, loading it from secrets if needed.
    Returns "UNKNOWN_BOT" if not yet configured or in bootstrap mode.
    """
    try:
        from tbot_bot.support.decrypt_secrets import load_bot_identity
        # Use bootstrap utility for guard
        try:
            from tbot_web.py.bootstrap_utils import is_first_bootstrap
            if is_first_bootstrap():
                return "UNKNOWN_BOT"
        except ImportError:
            pass
        identity = load_bot_identity()
        if not identity:
            return "UNKNOWN_BOT"
        return identity
    except Exception:
        return "UNKNOWN_BOT"
