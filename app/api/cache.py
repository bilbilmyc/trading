"""Simple TTL cache for hot endpoints that change rarely.

Wraps a callable result with expiry. Used for /config, /exchanges,
/health/venues — values that change at most a few times per minute.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any


class TTLCache:
    def __init__(self, default_ttl: float = 30.0) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        ttl: float | None = None,
    ) -> Any:
        now = time.monotonic()
        async with self._lock:
            entry = self._store.get(key)
            if entry is not None and entry[0] > now:
                return entry[1]
        # Miss — compute outside the lock to avoid blocking other gets.
        value = await factory()
        async with self._lock:
            self._store[key] = (now + (ttl or self._default_ttl), value)
        return value

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)

    def stats(self) -> dict[str, Any]:
        now = time.monotonic()
        alive = sum(1 for ts, _ in self._store.values() if ts > now)
        return {"size": len(self._store), "alive": alive}


__all__ = ["TTLCache"]
