"""TickerCache — TTL cache for get_ticker calls.

Multiple consumers (LiveOrderPipeline, RiskManager, frontend) requesting
the same symbol within the TTL window share one underlying exchange call.
Concurrent requests for the same key collapse to a single in-flight fetch.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _Entry:
    value: dict[str, Any]
    expires_at: float
    lock: asyncio.Lock
    in_flight: asyncio.Task | None = None


class TickerCache:
    """Wraps an exchange-like object with `async get_ticker(symbol)`.

    Args:
        fetch: callable `(symbol) -> Awaitable[dict]` — typically
            `ExchangeBase.get_ticker`. Tests can pass a FakeExchange.
        ttl_seconds: how long a cached ticker stays valid. Set to ~1s
            for signal loops; 0 disables caching.
    """

    def __init__(
        self,
        fetch: Any,
        ttl_seconds: float = 1.0,
    ) -> None:
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._store: dict[str, _Entry] = {}
        self._global_lock = asyncio.Lock()
        self.hits = 0
        self.misses = 0

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        now = time.monotonic()
        entry = self._store.get(symbol)
        if entry is not None and entry.expires_at > now:
            self.hits += 1
            return entry.value

        # Per-key lock prevents two concurrent fetches for the same symbol.
        if entry is None:
            async with self._global_lock:
                entry = self._store.get(symbol)
                if entry is None:
                    entry = _Entry(value={}, expires_at=0, lock=asyncio.Lock())
                    self._store[symbol] = entry
        async with entry.lock:
            # Re-check after acquiring — another coroutine may have just populated.
            if entry.expires_at > time.monotonic():
                self.hits += 1
                return entry.value
            self.misses += 1
            value = await self._fetch.get_ticker(symbol)
            entry.value = dict(value)
            entry.expires_at = time.monotonic() + self._ttl
            return entry.value

    def invalidate(self, symbol: str) -> None:
        entry = self._store.get(symbol)
        if entry is not None:
            entry.expires_at = 0.0

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": (self.hits / total) if total else 0.0,
            "size": len(self._store),
        }


__all__ = ["TickerCache"]
