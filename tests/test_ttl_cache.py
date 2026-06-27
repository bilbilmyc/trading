"""Tests for TTLCache."""

import asyncio
import pytest

from app.api.cache import TTLCache


@pytest.mark.asyncio
async def test_cache_stores_first_value() -> None:
    cache = TTLCache(default_ttl=10.0)
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        return "value-1"

    v = await cache.get_or_set("k", factory)
    assert v == "value-1"
    assert call_count == 1


@pytest.mark.asyncio
async def test_cache_returns_cached_value() -> None:
    cache = TTLCache(default_ttl=10.0)
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        return "x"

    await cache.get_or_set("k", factory)
    v = await cache.get_or_set("k", factory)
    assert v == "x"
    assert call_count == 1  # second call hit cache


@pytest.mark.asyncio
async def test_cache_expires_after_ttl() -> None:
    cache = TTLCache(default_ttl=0.05)
    call_count = 0

    async def factory():
        nonlocal call_count
        call_count += 1
        return f"v{call_count}"

    v1 = await cache.get_or_set("k", factory)
    await asyncio.sleep(0.1)
    v2 = await cache.get_or_set("k", factory)
    assert v1 != v2
    assert call_count == 2


@pytest.mark.asyncio
async def test_cache_per_key_ttl() -> None:
    cache = TTLCache()
    count = 0

    async def factory():
        nonlocal count
        count += 1
        return count

    v1 = await cache.get_or_set("a", factory, ttl=0.05)
    v2 = await cache.get_or_set("b", factory, ttl=10.0)
    await asyncio.sleep(0.1)
    v3 = await cache.get_or_set("a", factory, ttl=0.05)
    v4 = await cache.get_or_set("b", factory, ttl=10.0)
    assert v1 != v3  # a expired
    assert v2 == v4  # b cached


def test_invalidate_specific_key() -> None:
    cache = TTLCache()
    cache._store["k1"] = (999999.0, "x")
    cache._store["k2"] = (999999.0, "y")
    cache.invalidate("k1")
    assert "k1" not in cache._store
    assert "k2" in cache._store


def test_invalidate_all() -> None:
    cache = TTLCache()
    cache._store["a"] = (999999.0, 1)
    cache._store["b"] = (999999.0, 2)
    cache.invalidate()
    assert cache._store == {}


def test_stats() -> None:
    cache = TTLCache()
    cache._store["alive"] = (99999999999.0, "x")
    cache._store["dead"] = (0.0, "y")
    s = cache.stats()
    assert s["size"] == 2
    assert s["alive"] == 1
