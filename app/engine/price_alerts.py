"""Price alerts — user-defined thresholds that fire on cross.

Each rule specifies a symbol + direction + threshold. A tick() call
passes current prices and returns fired alerts. The SSE stream emits
these as 'price_alert' events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AlertDirection(str, Enum):
    ABOVE = "above"
    BELOW = "below"


@dataclass
class PriceAlertRule:
    id: str
    symbol: str
    exchange: str
    direction: AlertDirection
    threshold: float
    enabled: bool = True
    last_triggered: Optional[float] = None  # price at last fire


@dataclass
class FiredAlert:
    rule_id: str
    symbol: str
    exchange: str
    direction: AlertDirection
    threshold: float
    price: float
    timestamp: str = ""


class PriceAlertMonitor:
    def __init__(self) -> None:
        self._rules: Dict[str, PriceAlertRule] = {}

    def add(self, rule: PriceAlertRule) -> None:
        self._rules[rule.id] = rule

    def remove(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def list(self) -> List[PriceAlertRule]:
        return list(self._rules.values())

    def tick(
        self,
        prices: Dict[str, float],
    ) -> List[FiredAlert]:
        """Check all enabled rules against current prices.

        prices: {symbol: price}
        Returns fired alerts (one per rule per tick max — repeated fires
        are gated by re-crossing after a non-triggering tick).
        """
        fired: List[FiredAlert] = []
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            price = prices.get(rule.symbol)
            if price is None:
                continue
            triggered = self._is_triggered(rule, price)
            if triggered and rule.last_triggered != price:
                fired.append(FiredAlert(
                    rule_id=rule.id,
                    symbol=rule.symbol,
                    exchange=rule.exchange,
                    direction=rule.direction,
                    threshold=rule.threshold,
                    price=price,
                ))
                rule.last_triggered = price
            elif not triggered:
                # Reset so a re-cross fires again.
                rule.last_triggered = None
        return fired

    @staticmethod
    def _is_triggered(rule: PriceAlertRule, price: float) -> bool:
        if rule.direction == AlertDirection.ABOVE:
            return price >= rule.threshold
        return price <= rule.threshold


__all__ = ["AlertDirection", "PriceAlertRule", "FiredAlert", "PriceAlertMonitor"]