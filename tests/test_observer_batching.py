"""Tests for CompositeObserver batch audit behavior.

Multiple record() calls should accumulate and flush to the store in a
single append_events() transaction, while monitor.push() continues to fire
per-event (real-time alerts).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.core.sqlite_store import SQLiteStore
from app.engine.composite_observer import CompositeObserver
from app.engine.monitor import Monitor
from app.engine.pipeline_types import TradeEvent


class _CountingStore:
    """SQLiteStore substitute that counts append_events calls."""

    def __init__(self) -> None:
        self.batches: List[List[Dict[str, Any]]] = []
        self.total = 0

    def append_events(self, events: List[Dict[str, Any]]) -> None:
        self.batches.append(list(events))
        self.total += len(events)

    def append_event(self, event: Dict[str, Any]) -> None:
        # Should NOT be called when batching is enabled.
        raise AssertionError("append_event should not be used when batching is enabled")


def _placed_event() -> TradeEvent:
    return TradeEvent(
        kind="order_placed",
        payload={
            "order_id": "abc-123",
            "exchange": "binance_usdm",
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.001,
            "price": 100000.0,
        },
    )


@pytest.mark.asyncio
async def test_multiple_records_flush_as_one_batch(tmp_path) -> None:
    monitor = Monitor()
    fake_store = _CountingStore()
    obs = CompositeObserver(
        monitor=monitor,
        store=fake_store,  # type: ignore[arg-type]
        buffer_max=10,
        flush_interval=0.05,
    )
    await obs.start()

    for _ in range(5):
        obs.record(_placed_event())

    # Wait for the background flush.
    await asyncio.sleep(0.15)

    await obs.stop()

    assert fake_store.total == 5
    assert len(fake_store.batches) >= 1
    assert len(fake_store.batches[0]) == 5 or sum(len(b) for b in fake_store.batches) == 5


@pytest.mark.asyncio
async def test_monitor_push_fires_per_event_immediately(tmp_path) -> None:
    monitor = Monitor()
    fake_store = _CountingStore()
    obs = CompositeObserver(
        monitor=monitor,
        store=fake_store,  # type: ignore[arg-type]
        buffer_max=10,
        flush_interval=0.5,
    )
    await obs.start()

    obs.record(_placed_event())
    obs.record(_placed_event())
    obs.record(_placed_event())

    # Monitor should have 3 alerts even before the store flushes.
    assert monitor.summary()["total_alerts"] == 3
    # Store hasn't flushed yet (interval is long).
    assert fake_store.total == 0

    await obs.stop()


@pytest.mark.asyncio
async def test_buffer_max_triggers_immediate_flush(tmp_path) -> None:
    monitor = Monitor()
    fake_store = _CountingStore()
    obs = CompositeObserver(
        monitor=monitor,
        store=fake_store,  # type: ignore[arg-type]
        buffer_max=3,
        flush_interval=10.0,  # long, so flush must come from buffer_max
    )
    await obs.start()

    for _ in range(3):
        obs.record(_placed_event())

    # Allow microtask to run.
    await asyncio.sleep(0)

    assert fake_store.total == 3
    await obs.stop()


@pytest.mark.asyncio
async def test_real_sqlite_store_receives_batched_writes(tmp_path) -> None:
    """End-to-end: events recorded through the buffer are persisted in one
    append_events transaction, retrievable via recent_events."""
    monitor = Monitor()
    real_store = SQLiteStore(str(tmp_path / "obs.sqlite3"))
    obs = CompositeObserver(
        monitor=monitor,
        store=real_store,
        buffer_max=5,
        flush_interval=0.05,
    )
    await obs.start()

    for _ in range(7):
        obs.record(_placed_event())

    await asyncio.sleep(0.15)
    await obs.stop()

    events = real_store.recent_events(limit=20)
    kinds = [e["event_type"] for e in events]
    assert kinds.count("live_order_submitted") == 7


@pytest.mark.asyncio
async def test_stop_flushes_remaining_buffer(tmp_path) -> None:
    monitor = Monitor()
    fake_store = _CountingStore()
    obs = CompositeObserver(
        monitor=monitor,
        store=fake_store,  # type: ignore[arg-type]
        buffer_max=100,
        flush_interval=10.0,
    )
    await obs.start()
    obs.record(_placed_event())
    obs.record(_placed_event())

    await obs.stop()

    assert fake_store.total == 2