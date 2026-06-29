"""Trailing stop-loss — auto-adjust SL as price moves in favorable direction.

Stateful: caller holds a TrailingStop and updates it with each new
price. The stop ratchets toward the entry side as price moves favorably,
never loosens.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class TrailingStop:
    """Trailing stop tracker.

    ratchet_pct: how far behind the peak the stop trails (0.01 = 1%).
    activation_pct: when the position is in profit by this fraction,
    start trailing (0.005 = 0.5%). 0 means start immediately.
    """

    side: Side
    entry_price: float
    ratchet_pct: float = 0.01
    activation_pct: float = 0.005
    _initial_stop: float | None = None
    _current_stop: float | None = None
    _peak: float | None = None
    _triggered: bool = False
    _hit: bool = False
    _hit_price: float | None = None

    def __post_init__(self) -> None:
        if self.ratchet_pct < 0 or self.ratchet_pct >= 1:
            raise ValueError("ratchet_pct must be in [0, 1)")
        if self.activation_pct < 0 or self.activation_pct >= 1:
            raise ValueError("activation_pct must be in [0, 1)")

    def update(self, price: float) -> bool:
        """Update with a new price. Returns True if the trailing stop was hit."""
        if self._hit:
            return True  # already triggered

        # Track peak in the favorable direction.
        if self._peak is None:
            self._peak = price
        elif self.side == Side.LONG and price > self._peak:
            self._peak = price
        elif self.side == Side.SHORT and price < self._peak:
            self._peak = price

        # Activation: only start trailing after profit threshold.
        if not self._triggered:
            if self.side == Side.LONG:
                profit_pct = (price - self.entry_price) / self.entry_price
                if profit_pct >= self.activation_pct:
                    self._triggered = True
                    # Initialize stop at activation point.
                    self._initial_stop = price * (1 - self.ratchet_pct)
                    self._current_stop = self._initial_stop
            else:  # SHORT
                profit_pct = (self.entry_price - price) / self.entry_price
                if profit_pct >= self.activation_pct:
                    self._triggered = True
                    self._initial_stop = price * (1 + self.ratchet_pct)
                    self._current_stop = self._initial_stop
            return False

        # Ratchet the stop in the favorable direction only.
        if self.side == Side.LONG:
            new_stop = price * (1 - self.ratchet_pct)
            if new_stop > (self._current_stop or 0):
                self._current_stop = new_stop
            # Trigger: price drops to or below stop.
            if price <= (self._current_stop or 0):
                self._hit = True
                self._hit_price = price
                return True
        else:  # SHORT
            new_stop = price * (1 + self.ratchet_pct)
            if new_stop < (self._current_stop or float("inf")):
                self._current_stop = new_stop
            # Trigger: price rises to or above stop.
            if price >= (self._current_stop or float("inf")):
                self._hit = True
                self._hit_price = price
                return True
        return False

    @property
    def current_stop(self) -> float | None:
        return self._current_stop

    @property
    def triggered(self) -> bool:
        return self._triggered

    @property
    def hit(self) -> bool:
        return self._hit

    @property
    def hit_price(self) -> float | None:
        return self._hit_price

    @property
    def peak(self) -> float | None:
        return self._peak

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == Side.LONG:
            return current_price - self.entry_price
        return self.entry_price - current_price


__all__ = ["Side", "TrailingStop"]
