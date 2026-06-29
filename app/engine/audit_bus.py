"""AuditEventBus — broadcast audit events to SSE subscribers.

In-process pub/sub. Subscribers get an asyncio.Queue per session; the
SSE endpoint drains each subscriber's queue into the wire. Bounded
in-memory history for late-attaching subscribers.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class AuditEvent:
    kind: str
    payload: dict[str, Any]
    severity: str = "info"
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditEventBus:
    def __init__(self, max_history: int = 500, queue_maxsize: int = 100) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._history: list[AuditEvent] = []
        self._max_history = max_history
        self._queue_maxsize = queue_maxsize
        self._lock = asyncio.Lock()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers.append(queue)
        # Drain history so late subscribers catch up on existing events.
        for event in self._history:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                break
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def history(self) -> list[AuditEvent]:
        return list(self._history)

    async def publish(self, event: AuditEvent) -> None:
        async with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]
            # Best-effort fanout — drop on slow subscribers.
            for q in list(self._subscribers):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    # Slow consumer — drop and let them catch up via SSE miss.
                    pass


__all__ = ["AuditEvent", "AuditEventBus"]
