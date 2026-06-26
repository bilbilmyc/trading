"""Funding rate tracking for perpetual contracts.

Pure-function: keep a small in-memory history of funding rates per
(symbol, exchange). Used by the funding rate visualization in the UI
and by the periodic funding-cost calc on open positions.

Perpetual contracts pay/receive funding every N hours. Positive rate
means longs pay shorts; negative means shorts pay longs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FundingSnapshot:
    symbol: str
    exchange: str
    rate: float              # e.g. 0.0001 = 0.01% per 8h
    next_settlement_ms: Optional[int] = None
    timestamp: str = ""


@dataclass
class FundingHistory:
    snapshots: List[FundingSnapshot] = field(default_factory=list)

    def add(self, snap: FundingSnapshot) -> None:
        self.snapshots.append(snap)
        # Bound at 1000 entries per (symbol, exchange) to avoid unbounded growth.
        if len(self.snapshots) > 1000:
            self.snapshots = self.snapshots[-1000:]

    def latest(self) -> Optional[FundingSnapshot]:
        return self.snapshots[-1] if self.snapshots else None

    def annualized_rate(self) -> Optional[float]:
        """Convert latest funding rate to annualized basis.

        Assumes 8h funding cycle (3 settlements per day). Real exchange
        cycle varies (1h, 4h, 8h) — caller should pass the right multiplier
        in production. Default 3x/day here keeps the module testable.
        """
        latest = self.latest()
        if latest is None:
            return None
        return latest.rate * 3 * 365


class FundingTracker:
    """Tracks funding rate history keyed by (symbol, exchange)."""

    def __init__(self, settlements_per_day: int = 3) -> None:
        self._store: Dict[tuple, FundingHistory] = {}
        self.settlements_per_day = settlements_per_day

    def record(self, snap: FundingSnapshot) -> None:
        key = (snap.symbol.upper(), snap.exchange.lower())
        hist = self._store.setdefault(key, FundingHistory())
        hist.add(snap)

    def history(self, symbol: str, exchange: str) -> FundingHistory:
        return self._store.setdefault(
            (symbol.upper(), exchange.lower()), FundingHistory()
        )

    def latest(self, symbol: str, exchange: str) -> Optional[FundingSnapshot]:
        return self.history(symbol, exchange).latest()

    def all_pairs(self) -> List[tuple]:
        return list(self._store.keys())


__all__ = ["FundingSnapshot", "FundingHistory", "FundingTracker"]