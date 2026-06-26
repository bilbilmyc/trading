"""Tests for CompositeObserver — alert + audit event emission."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.core.sqlite_store import SQLiteStore
from app.engine.composite_observer import CompositeObserver
from app.engine.monitor import Monitor
from app.engine.pipeline_types import TradeEvent


async def _make_observer(tmp_path: Path) -> tuple:
    store = SQLiteStore(str(tmp_path / "obs.sqlite3"))
    monitor = Monitor()
    obs = CompositeObserver(monitor, store, flush_interval=0.05)
    await obs.start()
    return obs, store, monitor


@pytest.mark.asyncio
async def test_order_placed_emits_alert_and_event(tmp_path: Path) -> None:
    obs, store, monitor = await _make_observer(tmp_path)
    obs.record(TradeEvent(
        kind="order_placed",
        payload={
            "order_id": "abc-123",
            "exchange": "binance_usdm",
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.001,
            "price": 100000.0,
        },
    ))
    await asyncio.sleep(0.1)
    await obs.stop()

    alerts = monitor.summary()
    assert alerts["total_alerts"] >= 1

    events = store.recent_events(limit=10)
    kinds = [e["event_type"] for e in events]
    assert "live_order_submitted" in kinds


@pytest.mark.asyncio
async def test_risk_rejected_emits_warning_alert_and_audit_event(tmp_path: Path) -> None:
    obs, store, monitor = await _make_observer(tmp_path)
    obs.record(TradeEvent(
        kind="risk_rejected",
        payload={
            "reason": "max position value exceeded",
            "exchange": "binance_usdm",
            "symbol": "BTCUSDT",
        },
    ))
    await asyncio.sleep(0.1)
    await obs.stop()

    events = store.recent_events(limit=10)
    kinds = [e["event_type"] for e in events]
    assert "order_rejected_by_risk" in kinds


@pytest.mark.asyncio
async def test_order_failed_emits_error_alert(tmp_path: Path) -> None:
    obs, store, monitor = await _make_observer(tmp_path)
    obs.record(TradeEvent(
        kind="order_failed",
        payload={"error": "exchange down", "symbol": "BTCUSDT", "exchange": "binance_usdm"},
    ))
    await asyncio.sleep(0.1)
    await obs.stop()

    events = store.recent_events(limit=10)
    kinds = [e["event_type"] for e in events]
    assert "live_order_failed" in kinds


@pytest.mark.asyncio
async def test_gate_blocked_emits_critical_event(tmp_path: Path) -> None:
    obs, store, _ = await _make_observer(tmp_path)
    obs.record(TradeEvent(
        kind="gate_blocked",
        payload={"exchange": "binance_usdm", "symbol": "BTCUSDT"},
    ))
    await asyncio.sleep(0.1)
    await obs.stop()

    events = store.recent_events(limit=10)
    kinds = [e["event_type"] for e in events]
    levels = [e["level"] for e in events]
    assert "kill_switch_blocked" in kinds
    assert "critical" in levels


@pytest.mark.asyncio
async def test_observer_works_without_store() -> None:
    """A None store should still allow alerts but skip audit events."""
    monitor = Monitor()
    obs = CompositeObserver(monitor, store=None, flush_interval=0.05)
    await obs.start()
    obs.record(TradeEvent(
        kind="order_placed",
        payload={
            "order_id": "abc",
            "exchange": "binance_usdm",
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.001,
            "price": 100000.0,
        },
    ))
    assert monitor.summary()["total_alerts"] >= 1
    await obs.stop()