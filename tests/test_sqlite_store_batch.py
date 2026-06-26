"""Tests for batched SQLite event writes — reduces fsync overhead."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.core.sqlite_store import SQLiteStore


def _event(i: int) -> dict:
    return {
        "category": "test",
        "event_type": "batch_test",
        "level": "info",
        "exchange": "binance_usdm",
        "symbol": "BTCUSDT",
        "message": f"event {i}",
        "details": {"i": i},
        "timestamp": datetime.utcnow().isoformat(),
    }


def test_append_event_still_works(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "batch.sqlite3"))
    store.append_event(_event(1))
    events = store.recent_events(limit=10)
    assert len(events) == 1
    assert events[0]["message"] == "event 1"


def test_append_events_batch_writes_all_in_one_transaction(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "batch.sqlite3"))
    events = [_event(i) for i in range(50)]
    store.append_events(events)
    fetched = store.recent_events(limit=100)
    assert len(fetched) == 50
    # Order is preserved by insertion; compare numerically, not lexically.
    nums = sorted(int(e["message"].split()[1]) for e in fetched)
    assert nums == list(range(50))


def test_append_events_empty_list_is_noop(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "batch.sqlite3"))
    store.append_events([])  # should not raise
    assert store.recent_events(limit=10) == []


def test_batch_is_faster_than_per_event_commits(tmp_path) -> None:
    """Hammer the same N events: batched version should commit less."""
    import time

    n = 200

    store_a = SQLiteStore(str(tmp_path / "a.sqlite3"))
    store_b = SQLiteStore(str(tmp_path / "b.sqlite3"))

    events = [_event(i) for i in range(n)]

    t0 = time.perf_counter()
    for e in events:
        store_a.append_event(e)
    per_event_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    store_b.append_events(events)
    batch_ms = (time.perf_counter() - t0) * 1000

    # Batch should be measurably faster; allow generous margin for slow CI.
    assert batch_ms < per_event_ms, (
        f"batch ({batch_ms:.1f}ms) should beat per-event ({per_event_ms:.1f}ms)"
    )
    # Sanity: both stored the same count
    assert len(store_a.recent_events(limit=n)) == n
    assert len(store_b.recent_events(limit=n)) == n


def test_batch_with_mixed_event_shapes(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "mixed.sqlite3"))
    store.append_events([
        _event(0),  # has all optional fields
        {"category": "alert", "event_type": "minimal", "message": "bare", "timestamp": datetime.utcnow().isoformat()},
        {"category": "order", "event_type": "with_id", "level": "warning",
         "order_id": "abc-123", "message": "with id", "timestamp": datetime.utcnow().isoformat()},
    ])
    fetched = store.recent_events(limit=10)
    assert len(fetched) == 3
    by_msg = {e["message"]: e for e in fetched}
    assert by_msg["bare"]["level"] == "info"
    assert by_msg["bare"]["exchange"] is None
    assert by_msg["with id"]["order_id"] == "abc-123"


def test_batch_serializes_details_json(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "json.sqlite3"))
    store.append_events([{
        "category": "x", "event_type": "y",
        "message": "m", "details": {"complex": [1, 2, {"nested": True}]},
        "timestamp": datetime.utcnow().isoformat(),
    }])
    fetched = store.recent_events(limit=1)
    assert fetched[0]["details"] == {"complex": [1, 2, {"nested": True}]}