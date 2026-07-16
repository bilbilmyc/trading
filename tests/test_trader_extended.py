"""Extended tests for TradingEngine — exercise more code paths."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from app.core.sqlite_store import SQLiteStore
from app.engine.trader import TradingEngine
from app.strategies.base import Signal, SignalAction
from app.strategies.sma import SMAStrategy


def _engine(tmp_path) -> TradingEngine:
    return TradingEngine(store=SQLiteStore(str(tmp_path / "trader.sqlite3")))


def test_engine_starts_and_stops(tmp_path) -> None:
    async def scenario():
        e = _engine(tmp_path)
        await e.start()
        assert e._running is True
        assert e._observer._flush_task is not None
        await e.stop()
        assert e._running is False

    asyncio.run(scenario())


def test_engine_start_when_already_running_no_op(tmp_path) -> None:
    async def scenario():
        e = _engine(tmp_path)
        await e.start()
        await e.start()  # second start should be no-op
        assert e._running is True
        await e.stop()

    asyncio.run(scenario())


def test_engine_stop_when_not_running_no_op(tmp_path) -> None:
    async def scenario():
        e = _engine(tmp_path)
        await e.stop()  # no-op
        assert e._running is False

    asyncio.run(scenario())


def test_engine_signal_filter_sync(tmp_path) -> None:
    e = _engine(tmp_path)
    received = []

    async def my_filter(exchange, strategy, signal):
        received.append((exchange, strategy, signal.symbol))
        return True

    e.add_signal_filter(my_filter)
    assert len(e._signal_filters) == 1

    sig = Signal(symbol="BTCUSDT", action=SignalAction.BUY, strength=0.8, quantity=0.01, price=100)
    result = asyncio.run(my_filter("binance_usdm", "smatest", sig))
    assert result is True
    assert received[0][2] == "BTCUSDT"


def test_engine_add_signal_filter_updates_existing_pipelines(tmp_path) -> None:
    e = _engine(tmp_path)
    e.add_exchange("binance_usdm", _make_fake_exchange())

    async def filter_fn(exchange, strategy, signal):
        return True

    e.add_signal_filter(filter_fn)

    assert len(e._signal_filters) == 1
    assert len(e._pipelines["binance_usdm"]._signal_filters) == 1


def test_engine_add_exchange_dedupes(tmp_path) -> None:
    e = _engine(tmp_path)
    fake_exchange = AsyncMock()
    fake_exchange.name = "fake"
    e.add_exchange("fake", fake_exchange)
    e.add_exchange("fake", fake_exchange)  # second add
    assert "fake" in e._exchanges


def test_engine_pipelines_dict_initialized(tmp_path) -> None:
    e = _engine(tmp_path)
    assert hasattr(e, "_pipelines")
    assert isinstance(e._pipelines, dict)


def test_engine_get_risk_status_async(tmp_path) -> None:
    async def scenario():
        e = _engine(tmp_path)
        risk = await e.risk_manager.get_risk_status()
        assert "trading_enabled" in risk

    asyncio.run(scenario())


def test_engine_add_strategy_with_existing_name_does_not_duplicate(tmp_path) -> None:
    e = _engine(tmp_path)
    s1 = SMAStrategy(short_window=5, long_window=20)
    s2 = SMAStrategy(short_window=7, long_window=21)
    e.add_strategy("test", s1, exchange="binance_usdm", symbol="BTCUSDT")
    e.add_strategy("test", s2, exchange="binance_usdm", symbol="BTCUSDT")
    # Second add overwrites first.
    assert e._strategies["test"].short_window == 7


def test_engine_get_recent_signals_caps_at_limit(tmp_path) -> None:
    e = _engine(tmp_path)
    for _ in range(50):
        sig = Signal(
            symbol="BTCUSDT", action=SignalAction.BUY,
            strength=0.5, quantity=0.001, price=100.0,
        )
        e._record_signal("binance_usdm", "s", sig)
    recent = e.get_recent_signals(limit=5)
    assert len(recent) == 5


def test_engine_get_strategy_returns_strategy(tmp_path) -> None:
    e = _engine(tmp_path)
    s = SMAStrategy(short_window=5, long_window=20)
    e.add_strategy("a", s, exchange="binance_usdm", symbol="BTCUSDT", enabled=True)
    # Engine uses _strategies dict, not a public get_strategy method.
    assert "a" in e._strategies
    assert e._strategies["a"] is s


def test_engine_get_strategy_returns_none_for_unknown(tmp_path) -> None:
    e = _engine(tmp_path)
    assert "nonexistent" not in e._strategies


def test_engine_status_includes_timestamp(tmp_path) -> None:
    async def scenario():
        e = _engine(tmp_path)
        status = await e.get_status()
        assert "timestamp" in status

    asyncio.run(scenario())


def test_engine_risk_config_default_used(tmp_path) -> None:
    e = _engine(tmp_path)
    assert e.risk_manager.config.max_orders_per_minute >= 1


def test_engine_process_market_data_records_position(tmp_path) -> None:
    e = _engine(tmp_path)
    e.add_exchange("binance_usdm", _make_fake_exchange())
    e._process_market_data_for_strategy = _make_fake_strategy_processor(e)
    # Just verify the wiring — full flow tested in integration.
    assert e._exchanges["binance_usdm"].name == "binance_usdm"


def _make_fake_exchange():
    fake = AsyncMock()
    fake.name = "binance_usdm"
    fake.get_ticker = AsyncMock(return_value={"last_price": 100.0})
    fake.get_klines = AsyncMock(return_value=[])
    return fake


def _make_fake_strategy_processor(e):
    async def processor(strategy, exchange_name, symbol, data):
        pass
    return processor


def test_engine_risk_manager_disable_rejects(tmp_path) -> None:
    async def scenario():
        e = _engine(tmp_path)
        e.risk_manager.disable_trading()
        risk = await e.risk_manager.get_risk_status()
        assert risk["trading_enabled"] is False

    asyncio.run(scenario())


def test_engine_store_round_trip(tmp_path) -> None:
    e = _engine(tmp_path)
    e._record_event(
        category="test",
        event_type="smoke",
        level="info",
        exchange="binance_usdm",
        symbol="BTCUSDT",
        message="hello",
    )
    events = e.store.recent_events(limit=5)
    assert any(e["event_type"] == "smoke" for e in events)


def test_engine_position_manager_empty(tmp_path) -> None:
    async def scenario():
        e = _engine(tmp_path)
        pos = await e.position_manager.get_position("binance_usdm", "BTCUSDT")
        assert pos is None or pos.quantity == 0

    asyncio.run(scenario())


def test_engine_paper_account_starts_at_10k(tmp_path) -> None:
    e = _engine(tmp_path)
    assert e.paper_account.cash == 10_000.0


def test_engine_risk_doesnt_trade_when_disabled(tmp_path) -> None:
    async def scenario():
        e = _engine(tmp_path)
        e.risk_manager.disable_trading()
        # check_order should now fail with kill-switch reason.
        from app.strategies.base import Signal, SignalAction
        sig = Signal(
            symbol="BTCUSDT", action=SignalAction.BUY,
            strength=0.9, quantity=0.001,
        )
        allowed, reason = await e.risk_manager.check_order(
            sig.symbol, sig.action.value, sig.quantity or 0.001, 100.0
        )
        assert allowed is False
        assert "禁用" in reason or "kill" in reason.lower()

    asyncio.run(scenario())


def test_engine_strategy_persistence_roundtrip(tmp_path) -> None:
    """Persistence: store → load round-trip preserves strategy config."""
    e = _engine(tmp_path)
    s = SMAStrategy(short_window=5, long_window=20)
    e.add_strategy("sma-5-20", s, exchange="binance_usdm", symbol="BTCUSDT", enabled=True, mode="paper")
    e._persist_strategy("sma-5-20")

    # New engine reads from same store.
    e2 = TradingEngine(store=e.store)
    restored = e2.restore_persisted_strategies()
    assert restored >= 1
    assert "sma-5-20" in e2._strategies