"""Real-time price feed — multi-subscriber broadcaster for live tickers.

The exchange adapters push price updates here. Subscribers (SSE
endpoints, paper trader, monitoring) receive updates in near-real-time.

Lightweight: no message queue, no external broker. In-process async
queues per subscriber. Slow consumers fall behind — drop policy drops
oldest events for that subscriber.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PriceTick:
    source: str
    symbol: str
    price: float
    timestamp: str
    extra: dict[str, Any] = field(default_factory=dict)


class PriceFeed:
    """In-process pub/sub for price ticks.

    Subscribers get an asyncio.Queue per session. The feed drops events
    for slow consumers (queue full) rather than blocking the publisher.
    """

    def __init__(self, max_queue: int = 256) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._max_queue = max_queue
        self._latest: dict[str, PriceTick] = {}
        self._lock = asyncio.Lock()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def latest(self, source: str, symbol: str) -> PriceTick | None:
        return self._latest.get(f"{source}:{symbol}")

    def latest_all(self) -> list[PriceTick]:
        return list(self._latest.values())

    async def publish(self, tick: PriceTick) -> None:
        async with self._lock:
            self._latest[f"{tick.source}:{tick.symbol}"] = tick
            for q in list(self._subscribers):
                if q.full():
                    try:
                        q.get_nowait()  # drop oldest
                    except asyncio.QueueEmpty:
                        pass
                try:
                    q.put_nowait(tick)
                except asyncio.QueueFull:
                    pass

    def latest_dict(self) -> dict[str, dict[str, Any]]:
        """Return all latest prices as a JSON-serializable dict."""
        return {
            f"{t.source}:{t.symbol}": {
                "source": t.source,
                "symbol": t.symbol,
                "price": t.price,
                "timestamp": t.timestamp,
                "extra": t.extra,
            }
            for t in self._latest.values()
        }


__all__ = ["PriceTick", "PriceFeed"]
