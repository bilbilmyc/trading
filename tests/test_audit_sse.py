"""Tests for AuditEventBus — broadcast audit events to SSE subscribers."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.engine.audit_bus import AuditEventBus, AuditEvent


@pytest.mark.asyncio
async def test_subscribe_yields_initial_snapshot() -> None:
    bus = AuditEventBus()
    await bus.publish(AuditEvent(kind="order_placed", payload={"order_id": "x", "exchange": "binance_usdm", "symbol": "BTCUSDT"}))

    queue = bus.subscribe()
    event = queue.get_nowait()
    assert event.kind == "order_placed"
    assert event.payload["order_id"] == "x"


@pytest.mark.asyncio
async def test_publish_after_subscribe_delivers_to_subscriber() -> None:
    bus = AuditEventBus()
    queue = bus.subscribe()
    await bus.publish(AuditEvent(kind="risk_rejected", payload={"reason": "x", "exchange": "binance_usdm", "symbol": "BTCUSDT"}))
    event = await asyncio.wait_for(queue.get(), timeout=0.5)
    assert event.kind == "risk_rejected"


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery() -> None:
    bus = AuditEventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    await bus.publish(AuditEvent(kind="gate_blocked", payload={"exchange": "binance_usdm", "symbol": "BTCUSDT"}))
    assert queue.empty()


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive() -> None:
    bus = AuditEventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    await bus.publish(AuditEvent(kind="order_failed", payload={"error": "x", "exchange": "binance_usdm", "symbol": "BTCUSDT"}))
    e1 = await asyncio.wait_for(q1.get(), timeout=0.5)
    e2 = await asyncio.wait_for(q2.get(), timeout=0.5)
    assert e1.kind == e2.kind == "order_failed"


@pytest.mark.asyncio
async def test_history_buffer_bounded_at_max() -> None:
    bus = AuditEventBus(max_history=5)
    for i in range(20):
        await bus.publish(AuditEvent(kind="order_placed", payload={"i": i, "exchange": "binance_usdm", "symbol": "BTCUSDT"}))
    assert len(bus.history()) == 5


def test_audit_event_serializable_to_dict() -> None:
    e = AuditEvent(kind="order_placed", payload={"a": 1, "b": "x"}, severity="info", timestamp="2026-06-27T00:00:00")
    d = e.to_dict()
    assert d["kind"] == "order_placed"
    assert d["payload"]["a"] == 1
    # JSON-serializable
    json.dumps(d)


def test_audit_event_default_severity_is_info() -> None:
    e = AuditEvent(kind="gate_blocked", payload={"x": 1})
    assert e.severity == "info"
    assert e.timestamp == ""