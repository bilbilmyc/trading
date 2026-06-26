"""Tests for TickerCache wiring into LiveOrderPipeline.

When multiple signals fire within the TTL window, only one underlying
get_ticker() call should hit the exchange.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from app.engine.pipeline_types import RiskDecision
from app.engine.ticker_cache import TickerCache
from app.strategies.base import Signal, SignalAction


class FakeExchange:
    def __init__(self, ticker: Dict[str, Any] | None = None) -> None:
        self._ticker = ticker or {"last_price": 100.0}
        self.ticker_calls = 0

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        self.ticker_calls += 1
        return dict(self._ticker)

    async def place_order(self, **kwargs):
        return {"order_id": "fake-1"}


class AlwaysAllowedGate:
    async def check(self, signal, price):
        return RiskDecision(allowed=True, reason="ok")


class FakeGuard:
    async def is_open(self):
        return True


class NoOpTracker:
    def track(self, order): pass


class NoOpRecorder:
    async def record(self, receipt): pass


class NoOpObserver:
    def record(self, event): pass


@pytest.mark.asyncio
async def test_two_signals_within_ttl_share_one_ticker_fetch() -> None:
    from app.engine.live_order_pipeline import LiveOrderPipeline

    exchange = FakeExchange()
    cache = TickerCache(exchange, ttl_seconds=2.0)
    pipeline = LiveOrderPipeline(
        exchange=cache,  # cache wraps exchange — pipeline calls cache.get_ticker indirectly
        trading_guard=FakeGuard(),
        risk_gate=AlwaysAllowedGate(),
        order_tracker=NoOpTracker(),
        position_recorder=NoOpRecorder(),
        observer=NoOpObserver(),
        semaphore=asyncio.Semaphore(5),
    )

    sig = Signal(symbol="BTCUSDT", action=SignalAction.BUY, strength=0.9, quantity=0.001)
    await pipeline.execute(sig)
    await pipeline.execute(sig)

    assert exchange.ticker_calls == 1


@pytest.mark.asyncio
async def test_ticker_cache_miss_after_ttl_triggers_refetch() -> None:
    from app.engine.live_order_pipeline import LiveOrderPipeline

    exchange = FakeExchange()
    cache = TickerCache(exchange, ttl_seconds=0.05)
    pipeline = LiveOrderPipeline(
        exchange=cache,
        trading_guard=FakeGuard(),
        risk_gate=AlwaysAllowedGate(),
        order_tracker=NoOpTracker(),
        position_recorder=NoOpRecorder(),
        observer=NoOpObserver(),
        semaphore=asyncio.Semaphore(5),
    )

    sig = Signal(symbol="BTCUSDT", action=SignalAction.BUY, strength=0.9, quantity=0.001)
    await pipeline.execute(sig)
    await asyncio.sleep(0.1)
    await pipeline.execute(sig)

    assert exchange.ticker_calls == 2