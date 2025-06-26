# tbot_bot/test/test_ledger_schema.py
# Tests that new ledgers match COA/schema and double-entry enforcement
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.
# All process orchestration is via tbot_supervisor.py only.

import pytest
from tbot_bot.config.env_bot import get_bot_config

def test_strategy_selfchecks():
    """
    Confirms that all enabled strategies pass their .self_check() method.
    This is required before executing any session in production mode.
    Does not launch, run, or supervise any persistent process.
    """
    config = get_bot_config()
    failures = []

    if config.get("STRAT_OPEN_ENABLED"):
        try:
            from tbot_bot.strategy.strategy_open import self_check as check_open
            if not check_open():
                failures.append("strategy_open failed self_check()")
        except Exception as e:
            failures.append(f"strategy_open import/self_check error: {e}")

    if config.get("STRAT_MID_ENABLED"):
        try:
            from tbot_bot.strategy.strategy_mid import self_check as check_mid
            if not check_mid():
                failures.append("strategy_mid failed self_check()")
        except Exception as e:
            failures.append(f"strategy_mid import/self_check error: {e}")

    if config.get("STRAT_CLOSE_ENABLED"):
        try:
            from tbot_bot.strategy.strategy_close import self_check as check_close
            if not check_close():
                failures.append("strategy_close failed self_check()")
        except Exception as e:
            failures.append(f"strategy_close import/self_check error: {e}")

    assert not failures, "Self-check errors:\n" + "\n".join(failures)
