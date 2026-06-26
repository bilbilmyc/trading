"""Tests for TickerCache — dedupes get_ticker calls within a TTL window."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeExchange:
    def __init__(self, ticker: Dict[str, Any] | None = None) -> None:
        self._ticker = ticker or {"last_price": 100.0}
        self.calls = 0

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        self.calls += 1
        return dict(self._ticker)


@pytest.mark.asyncio
async def test_first_call_hits_exchange() -> None:
    from app.engine.ticker_cache import TickerCache

    ex = FakeExchange()
    cache = TickerCache(ex, ttl_seconds=1.0)

    result = await cache.get_ticker("BTCUSDT")

    assert result == {"last_price": 100.0}
    assert ex.calls == 1


@pytest.mark.asyncio
async def test_second_call_within_ttl_uses_cache() -> None:
    from app.engine.ticker_cache import TickerCache

    ex = FakeExchange()
    cache = TickerCache(ex, ttl_seconds=1.0)

    await cache.get_ticker("BTCUSDT")
    await cache.get_ticker("BTCUSDT")
    await cache.get_ticker("BTCUSDT")

    assert ex.calls == 1  # only one network roundtrip


@pytest.mark.asyncio
async def test_different_symbols_cache_separately() -> None:
    from app.engine.ticker_cache import TickerCache

    ex = FakeExchange()
    cache = TickerCache(ex, ttl_seconds=1.0)

    await cache.get_ticker("BTCUSDT")
    await cache.get_ticker("ETHUSDT")

    assert ex.calls == 2


@pytest.mark.asyncio
async def test_expired_entry_refetches() -> None:
    from app.engine.ticker_cache import TickerCache

    ex = FakeExchange()
    cache = TickerCache(ex, ttl_seconds=0.05)

    await cache.get_ticker("BTCUSDT")
    time.sleep(0.1)
    await cache.get_ticker("BTCUSDT")

    assert ex.calls == 2


@pytest.mark.asyncio
async def test_concurrent_calls_dedupe_to_one_fetch() -> None:
    """If N coroutines ask for the same ticker simultaneously, only one
    underlying fetch should happen."""
    from app.engine.ticker_cache import TickerCache

    class SlowExchange:
        def __init__(self) -> None:
            self.calls = 0

        async def get_ticker(self, symbol: str) -> Dict[str, Any]:
            self.calls += 1
            await asyncio.sleep(0.05)
            return {"last_price": 100.0, "symbol": symbol}

    ex = SlowExchange()
    cache = TickerCache(ex, ttl_seconds=1.0)

    results = await asyncio.gather(*[cache.get_ticker("BTCUSDT") for _ in range(5)])

    assert all(r == {"last_price": 100.0, "symbol": "BTCUSDT"} for r in results)
    assert ex.calls == 1


@pytest.mark.asyncio
async def test_invalidate_forces_refetch() -> None:
    from app.engine.ticker_cache import TickerCache

    ex = FakeExchange()
    cache = TickerCache(ex, ttl_seconds=10.0)

    await cache.get_ticker("BTCUSDT")
    cache.invalidate("BTCUSDT")
    await cache.get_ticker("BTCUSDT")

    assert ex.calls == 2