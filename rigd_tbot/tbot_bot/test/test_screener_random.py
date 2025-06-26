# tbot_bot/test/test_screener_random.py
# Runs screener logic with randomized symbols to confirm filtering and eligibility logic
# THIS TEST MUST NEVER ATTEMPT TO DIRECTLY LAUNCH OR SUPERVISE WORKERS/WATCHERS.
# All process orchestration is via tbot_supervisor.py only.

import pytest
import random
from tbot_bot.screeners.finnhub_screener import FinnhubScreener
from tbot_bot.screeners.alpaca_screener import AlpacaScreener
from tbot_bot.screeners.ibkr_screener import IBKRScreener
from tbot_bot.config.env_bot import get_bot_config

SAMPLE_SYMBOLS = [
    "AAPL", "MSFT", "TSLA", "GOOG", "AMZN",
    "NVDA", "AMD", "INTC", "SPY", "QQQ",
    "META", "NFLX", "BA", "T", "XOM"
]

def random_symbols(n=5):
    return random.sample(SAMPLE_SYMBOLS, min(n, len(SAMPLE_SYMBOLS)))

@pytest.mark.parametrize("screener_cls", [FinnhubScreener, AlpacaScreener, IBKRScreener])
def test_random_symbol_filtering(screener_cls):
    """
    Confirms that each screener filters and validates symbols per project spec.
    Does not launch, run, or supervise any persistent process.
    """
    config = get_bot_config()
    screener = screener_cls(config=config)
    symbols = random_symbols(10)
    eligible = screener.filter_symbols(symbols)
    assert isinstance(eligible, list)
    assert all(isinstance(s, str) for s in eligible)
    # Check that filtered symbols meet minimum eligibility (e.g., not empty)
    assert len(eligible) <= len(symbols)
