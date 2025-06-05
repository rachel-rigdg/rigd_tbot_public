# path: tbot_bot/strategy/strategy_meta.py
# summary: StrategyResult container for inter-strategy communication

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class StrategyResult:
    trades: Optional[List[dict]] = None
    skipped: bool = False
    errors: Optional[List[str]] = None
