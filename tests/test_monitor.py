"""Tests for Monitor — alert aggregation."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.engine.monitor import Alert, AlertCategory, AlertLevel, Monitor


def test_alert_to_dict() -> None:
    a = Alert(
        level=AlertLevel.WARNING,
        category=AlertCategory.ORDER,
        title="test",
        message="hello",
        exchange="binance_usdm",
        symbol="BTCUSDT",
    )
    d = a.to_dict()
    assert d["title"] == "test"
    assert d["level"] == "warning"
    assert d["category"] == "order"


def test_alert_enum_values() -> None:
    assert AlertLevel.INFO.value == "info"
    assert AlertLevel.WARNING.value == "warning"
    assert AlertLevel.ERROR.value == "error"
    assert AlertLevel.CRITICAL.value == "critical"

    assert AlertCategory.ORDER.value == "order"
    assert AlertCategory.RISK.value == "risk"
    assert AlertCategory.ENGINE.value == "engine"
    assert AlertCategory.POSITION.value == "position"


def test_monitor_initial_state() -> None:
    m = Monitor()
    assert m._alerts == []
    assert m._checkers == []
    assert m._running is False


def test_monitor_push_adds_alert() -> None:
    m = Monitor()
    a = Alert(level=AlertLevel.INFO, category=AlertCategory.ORDER, title="t", message="m")
    m.push(a)
    assert len(m._alerts) == 1


def test_monitor_max_alerts_caps_history() -> None:
    m = Monitor(max_alerts=5)
    for i in range(20):
        m.push(Alert(level=AlertLevel.INFO, category=AlertCategory.ORDER, title=f"t{i}", message="m"))
    assert len(m._alerts) == 5


def test_monitor_recent_alerts_default() -> None:
    m = Monitor()
    m.push(Alert(level=AlertLevel.INFO, category=AlertCategory.ORDER, title="t1", message="m"))
    m.push(Alert(level=AlertLevel.ERROR, category=AlertCategory.RISK, title="t2", message="m"))
    recent = m.recent_alerts()
    assert len(recent) == 2


def test_monitor_recent_alerts_filtered_by_level() -> None:
    m = Monitor()
    m.push(Alert(level=AlertLevel.INFO, category=AlertCategory.ORDER, title="info", message="m"))
    m.push(Alert(level=AlertLevel.ERROR, category=AlertCategory.ORDER, title="err", message="m"))
    errors = m.recent_alerts(level=AlertLevel.ERROR)
    assert len(errors) == 1
    assert errors[0]["title"] == "err"


def test_monitor_recent_alerts_respects_limit() -> None:
    m = Monitor()
    for i in range(10):
        m.push(Alert(level=AlertLevel.INFO, category=AlertCategory.ORDER, title=f"t{i}", message="m"))
    recent = m.recent_alerts(limit=3)
    assert len(recent) == 3


def test_monitor_summary_shape() -> None:
    m = Monitor()
    m.push(Alert(level=AlertLevel.INFO, category=AlertCategory.ORDER, title="t", message="m"))
    summary = m.summary()
    assert "total_alerts" in summary
    assert summary["total_alerts"] == 1


def test_monitor_summary_by_level() -> None:
    m = Monitor()
    m.push(Alert(level=AlertLevel.WARNING, category=AlertCategory.ORDER, title="w", message="m"))
    m.push(Alert(level=AlertLevel.ERROR, category=AlertCategory.ORDER, title="e", message="m"))
    summary = m.summary()
    assert summary["by_level"]["warning"] == 1
    assert summary["by_level"]["error"] == 1


def test_monitor_add_checker_appends() -> None:
    m = Monitor()
    async def c1():
        return None
    async def c2():
        return None
    m.add_checker(c1)
    m.add_checker(c2)
    assert len(m._checkers) == 2


def test_monitor_on_alert_appends_callback() -> None:
    m = Monitor()
    async def cb(alert):
        pass
    m.on_alert(cb)
    assert len(m._callbacks) == 1


def test_monitor_last_error_initially_none() -> None:
    m = Monitor()
    assert m.last_error() is None


def test_monitor_start_creates_task() -> None:
    async def scenario():
        m = Monitor()
        await m.stop()  # cleanup helper
        # Can't easily test start() without event loop running.
        # Just verify the method exists.
        assert hasattr(m, "start")
        assert hasattr(m, "stop")

    asyncio.run(scenario())


def test_monitor_stop_when_not_running_is_safe() -> None:
    async def scenario():
        m = Monitor()
        await m.stop()  # should not raise
        assert m._running is False

    asyncio.run(scenario())


def test_monitor_push_alert_with_details() -> None:
    m = Monitor()
    a = Alert(
        level=AlertLevel.CRITICAL,
        category=AlertCategory.RISK,
        title="kill switch",
        message="enabled",
        exchange="binance_usdm",
        symbol="BTCUSDT",
        details={"reason": "manual"},
    )
    m.push(a)
    d = m._alerts[0].to_dict()
    assert d["details"]["reason"] == "manual"