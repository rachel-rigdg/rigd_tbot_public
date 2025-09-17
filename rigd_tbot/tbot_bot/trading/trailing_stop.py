# tbot_bot/trading/trailing_stop.py
# Single source of truth for bot-enforced trailing stop math & state.

from dataclasses import dataclass

@dataclass
class TrailingStopState:
    side: str                 # "long" or "short" (use "short" also for inverse-ETF buys)
    pct: float                # 0.02 for 2%
    peak: float = 0.0         # highest seen since entry (long)
    trough: float = 10**12    # lowest seen since entry (short)
    active: bool = True       # allow disable if broker-native used

    def register_tick(self, price: float) -> None:
        if not self.active:
            return
        if self.side == "long":
            if price > self.peak:
                self.peak = price
        else:  # short / inverse-ETF
            if price < self.trough:
                self.trough = price

    def exit_trigger_price(self) -> float | None:
        if not self.active:
            return None
        if self.side == "long" and self.peak > 0:
            return self.peak * (1.0 - self.pct)  # peak × 0.98
        if self.side != "long" and self.trough < 10**12:
            return self.trough * (1.0 + self.pct)  # trough × 1.02
        return None

    def should_exit(self, price: float) -> bool:
        t = self.exit_trigger_price()
        if t is None:
            return False
        if self.side == "long":
            return price <= t
        else:
            return price >= t
