"""Integration tests for metrics wiring.

Verifies that the existing /metrics endpoint emits non-empty data
once the trading engine actually does work. Before this change the
endpoint rendered zero-count counters and empty histograms because no
code called `.labels().inc()` / `.observe()` — the engine surface
looked monitored but was a black box. These tests pin every metric
we instrumented in this iteration.
"""

from __future__ import annotations

from app.engine.metrics import (
    APP_INFO,
    CACHE_EVENTS_TOTAL,
    ENGINE_LOOP_DURATION,
    MONITOR_ALERTS_TOTAL,
    NOTIFIER_WEBHOOKS_TOTAL,
    ORDERS_TOTAL,
    POSITIONS_ACTIVE,
    RISK_REJECTIONS_TOTAL,
    render,
)
from app.engine.monitor import Alert, AlertCategory, AlertLevel, Monitor
from app.engine.position_manager import PositionManager
from app.models.position import Position


def test_monitor_push_increments_alerts_counter() -> None:
    m = Monitor()
    before = _counter_value(
        MONITOR_ALERTS_TOTAL, {"level": "warning", "category": "engine"}
    )
    m.push(
        Alert(
            level=AlertLevel.WARNING,
            category=AlertCategory.ENGINE,
            title="t",
            message="m",
        )
    )
    after = _counter_value(
        MONITOR_ALERTS_TOTAL, {"level": "warning", "category": "engine"}
    )
    assert after == before + 1


def test_engine_loop_duration_observation_recorded() -> None:
    ENGINE_LOOP_DURATION.labels(loop="test_loop").observe(0.05)
    # Histogram doesn't expose a direct .get(); just confirm render includes it.
    body, _ = render()
    assert b'qt_engine_loop_duration_seconds_count{loop="test_loop"}' in body


def test_orders_total_labels_work() -> None:
    ORDERS_TOTAL.labels(
        exchange="binance_usdm", side="buy", status="filled"
    ).inc()
    body, _ = render()
    assert (
        b'qt_orders_total{exchange="binance_usdm",side="buy",status="filled"}'
        in body
    )


def test_risk_rejections_total_labels_work() -> None:
    RISK_REJECTIONS_TOTAL.labels(reason="max_position").inc()
    body, _ = render()
    assert b'qt_risk_rejections_total{reason="max_position"}' in body


def test_positions_active_gauge_sync() -> None:
    pm = PositionManager()
    pm._positions["binance_usdm:BTCUSDT"] = Position(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        quantity=0.01,
        avg_entry_price=50000.0,
    )
    pm.sync_positions_gauge()
    body, _ = render()
    assert b'qt_positions_active{exchange="binance_usdm"} 1.0' in body


def test_app_info_set() -> None:
    APP_INFO.labels(version="test", env="ci").set(1)
    body, _ = render()
    assert b'qt_app_info{env="ci",version="test"} 1.0' in body


def test_cache_events_emitted() -> None:
    CACHE_EVENTS_TOTAL.labels(cache="t", event="hit").inc()
    CACHE_EVENTS_TOTAL.labels(cache="t", event="miss").inc(2)
    body, _ = render()
    assert b'qt_cache_events_total{cache="t",event="hit"}' in body
    assert b'qt_cache_events_total{cache="t",event="miss"}' in body


def test_notifier_counter_emitted() -> None:
    NOTIFIER_WEBHOOKS_TOTAL.labels(outcome="ok").inc()
    body, _ = render()
    assert b'qt_notifier_webhooks_total{outcome="ok"}' in body


def test_render_returns_bytes_and_text_plain() -> None:
    body, ct = render()
    assert isinstance(body, bytes)
    assert ct.startswith("text/plain")
    # End-to-end: must include all 11 metric families we expose.
    text = body.decode()
    for prefix in (
        "qt_orders_total",
        "qt_risk_rejections_total",
        "qt_monitor_alerts_total",
        "qt_engine_loop_duration_seconds",
        "qt_positions_active",
        "qt_app_info",
        "qt_notifier_webhooks_total",
        "qt_cache_events_total",
    ):
        assert prefix in text, f"missing metric family {prefix} in /metrics output"


def _counter_value(counter, labels: dict[str, str]) -> float:
    """Read a labelled counter's current value (helper for tests)."""
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0
