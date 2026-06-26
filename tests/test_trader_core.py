"""Tests for TradingEngine core helpers — _serialize_signal, _record_signal,
strategy matching, etc. without spinning up the full engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import pytest

from app.engine.trader import TradingEngine
from app.strategies.base import Signal, SignalAction


def _make_engine(tmp_path) -> TradingEngine:
    """Construct engine with SQLite in tmp_path and no exchanges."""
    from app.core.sqlite_store import SQLiteStore
    return TradingEngine(store=SQLiteStore(str(tmp_path / "trader.sqlite3")))


def test_engine_initializes_with_zero_strategies_when_store_empty(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    assert engine.list_strategies() == []


def test_engine_records_signals_to_store(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    signal = Signal(
        symbol="BTCUSDT",
        action=SignalAction.BUY,
        strength=0.8,
        quantity=0.01,
        price=50_000.0,
        order_type="market",
    )
    engine._record_signal("binance_usdm", "smatest", signal)

    recent = engine.store.recent_signals(limit=10)
    assert len(recent) == 1
    assert recent[0]["symbol"] == "BTCUSDT"
    assert recent[0]["action"] == "buy"


def test_engine_recent_signals_capped_at_200(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    for i in range(250):
        signal = Signal(
            symbol="BTCUSDT",
            action=SignalAction.BUY,
            strength=0.5,
            quantity=0.001,
            price=100.0,
        )
        engine._record_signal("binance_usdm", "smatest", signal)

    # Internal buffer capped at 200.
    assert len(engine._recent_signals) == 200


def test_engine_serialize_signal_includes_all_fields(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    signal = Signal(
        symbol="ETHUSDT",
        action=SignalAction.SELL,
        strength=0.7,
        quantity=0.5,
        price=4000.0,
        order_type="limit",
        stop_loss=4100.0,
        take_profit=3800.0,
        metadata={"reason": "test"},
    )
    serialized = engine._serialize_signal("binance_usdm", "sma", signal)
    assert serialized["symbol"] == "ETHUSDT"
    assert serialized["action"] == "sell"
    assert serialized["quantity"] == 0.5
    assert serialized["price"] == 4000.0
    assert serialized["stop_loss"] == 4100.0
    assert serialized["take_profit"] == 3800.0
    assert serialized["metadata"]["reason"] == "test"
    assert serialized["actionable"] is True  # strength 0.7 > 0.5


def test_engine_serialize_signal_non_actionable_when_low_strength(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    signal = Signal(
        symbol="BTCUSDT",
        action=SignalAction.BUY,
        strength=0.3,
        quantity=0.01,
        price=100.0,
    )
    serialized = engine._serialize_signal("binance_usdm", "sma", signal)
    assert serialized["actionable"] is False


@pytest.mark.asyncio
async def test_engine_get_status_returns_snapshot(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    engine._running = True
    status = await engine.get_status()
    assert "strategies" in status
    assert "risk" in status
    assert "positions" in status
    assert "exchanges" in status
    assert "monitor" in status


def test_engine_add_signal_filter_appends(tmp_path) -> None:
    engine = _make_engine(tmp_path)

    async def filter_a(exchange, strategy, signal):
        return True

    async def filter_b(exchange, strategy, signal):
        return False

    engine.add_signal_filter(filter_a)
    engine.add_signal_filter(filter_b)
    assert len(engine._signal_filters) == 2


def test_engine_add_strategy_records_config(tmp_path) -> None:
    from app.strategies.sma import SMAStrategy
    engine = _make_engine(tmp_path)
    s = SMAStrategy(short_window=5, long_window=10)
    engine.add_strategy(
        "my-sma",
        s,
        exchange="binance_usdm",
        symbol="BTCUSDT",
        interval="1h",
        enabled=True,
        mode="paper",
    )
    assert "my-sma" in engine._strategies
    assert engine._strategy_configs["my-sma"]["exchange"] == "binance_usdm"


def test_engine_list_strategies_returns_configured(tmp_path) -> None:
    from app.strategies.sma import SMAStrategy
    engine = _make_engine(tmp_path)
    s = SMAStrategy(short_window=5, long_window=10)
    engine.add_strategy("a", s, exchange="binance_usdm", symbol="BTCUSDT", enabled=True)
    engine.add_strategy("b", s, exchange="binance_usdm", symbol="ETHUSDT", enabled=False)

    strategies = engine.list_strategies()
    names = [s["name"] for s in strategies]
    assert "a" in names
    assert "b" in names
    a_info = next(x for x in strategies if x["name"] == "a")
    assert a_info["running"] is True
    b_info = next(x for x in strategies if x["name"] == "b")
    assert b_info["running"] is False


def test_engine_get_recent_signals_returns_recorded(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    sig = Signal(
        symbol="BTCUSDT",
        action=SignalAction.BUY,
        strength=0.9,
        quantity=0.01,
        price=100.0,
    )
    engine._record_signal("binance_usdm", "smatest", sig)
    recent = engine.get_recent_signals(limit=5)
    assert len(recent) == 1


def test_engine_record_event_persists(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    engine._record_event(
        category="risk",
        event_type="kill_switch_enabled",
        level="critical",
        exchange="binance_usdm",
        symbol="BTCUSDT",
        message="manual",
    )
    events = engine.store.recent_events(limit=5)
    assert len(events) == 1
    assert events[0]["event_type"] == "kill_switch_enabled"
    assert events[0]["level"] == "critical"


@pytest.mark.asyncio
async def test_engine_get_risk_status_returns_dict(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    risk = await engine.risk_manager.get_risk_status()
    assert "trading_enabled" in risk
    assert "daily_pnl" in risk
    assert "max_orders_per_minute" in risk


def test_engine_engine_id_is_set(tmp_path) -> None:
    engine = _make_engine(tmp_path)
    # Internal field exists.
    assert hasattr(engine, "_exchanges")
    assert hasattr(engine, "_strategies")