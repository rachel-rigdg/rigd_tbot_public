# tbot_bot/support/utils_config.py
# Loads and validates bot and environment configuration

import sys

def get_bot_config():
    """
    Deferred loader for bot config—never crashes during bootstrap.
    Logs errors to stderr if loading fails.
    Guards against recursion by blocking if already in error.
    """
    if getattr(get_bot_config, "_recursing", False):
        print("[utils_config] ERROR loading bot config: recursion detected", file=sys.stderr)
        return {}
    get_bot_config._recursing = True
    try:
        from tbot_bot.config.env_bot import get_bot_config as load_config
        return load_config()
    except Exception as e:
        print(f"[utils_config] ERROR loading bot config: {e}", file=sys.stderr)
        return {}
    finally:
        get_bot_config._recursing = False
