"""Order book imbalance indicator — bid vs ask volume ratio.

Computed as (bid_volume - ask_volume) / (bid_volume + ask_volume).
Range: [-1, 1]. Positive = buy pressure, negative = sell pressure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence


@dataclass
class ImbalanceLevel:
    price: float
    quantity: float


@dataclass
class ImbalanceResult:
    bid_volume: float
    ask_volume: float
    imbalance: float          # -1..1
    signal: str               # "buy" | "sell" | "neutral"
    depth_ratio: float        # bid / ask (or inf if no asks)


def orderbook_imbalance(
    bids: Sequence[ImbalanceLevel],
    asks: Sequence[ImbalanceLevel],
) -> ImbalanceResult:
    """Compute imbalance over the given order book depth.

    bids: list of (price, quantity) sorted by price desc.
    asks: list of (price, quantity) sorted by price asc.
    """
    bid_vol = sum(b.quantity for b in bids)
    ask_vol = sum(a.quantity for a in asks)
    total = bid_vol + ask_vol
    if total == 0:
        return ImbalanceResult(0.0, 0.0, 0.0, "neutral", 0.0)
    imb = (bid_vol - ask_vol) / total
    if imb > 0.1:
        signal = "buy"
    elif imb < -0.1:
        signal = "sell"
    else:
        signal = "neutral"
    depth = bid_vol / ask_vol if ask_vol > 0 else float("inf")
    return ImbalanceResult(
        bid_volume=bid_vol,
        ask_volume=ask_vol,
        imbalance=round(imb, 4),
        signal=signal,
        depth_ratio=round(depth, 4) if depth != float("inf") else 9999.0,
    )


def orderbook_imbalance_top_n(
    bids: Sequence[ImbalanceLevel],
    asks: Sequence[ImbalanceLevel],
    depth: int = 5,
) -> ImbalanceResult:
    """Same as orderbook_imbalance but only consider top-N levels."""
    return orderbook_imbalance(bids[:depth], asks[:depth])


__all__ = [
    "ImbalanceLevel",
    "ImbalanceResult",
    "orderbook_imbalance",
    "orderbook_imbalance_top_n",
]