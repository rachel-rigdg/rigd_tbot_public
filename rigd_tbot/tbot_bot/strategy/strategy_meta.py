# path: tbot_bot/strategy/strategy_meta.py
# summary: StrategyResult container for inter-strategy communication

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class StrategyResult:
    trades: Optional[List[dict]] = field(default_factory=list)
    skipped: bool = False
    errors: Optional[List[str]] = field(default_factory=list)
