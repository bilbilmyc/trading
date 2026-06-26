"""Tests for GenericHttpDataSource — register a custom URL as a data source."""

from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from app.data_sources.generic_http import GenericHttpDataSource


def _json_response(body: Dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


@pytest.mark.asyncio
async def test_get_ticker_returns_normalized_dict() -> None:
    """Custom source returns a normalized ticker shape regardless of provider schema."""
    src = GenericHttpDataSource(
        name="my-venue",
        base_url="https://api.example.com/v1",
        ticker_path="/ticker/{symbol}",
        ticker_field_map={"last_price": "last", "volume_24h": "vol24h"},
    )

    captured: Dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["symbol"] = req.url.path.split("/")[-1]
        return _json_response({"last": 123.45, "vol24h": 9_000_000, "ignored": "x"})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    import app.data_sources.generic_http as mod

    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        ticker = await src.get_ticker("BTCUSDT")
    finally:
        mod.httpx.AsyncClient = real

    assert ticker["last_price"] == 123.45
    assert ticker["volume_24h"] == 9_000_000
    assert "ignored" not in ticker
    assert captured["url"].endswith("/ticker/BTCUSDT")


@pytest.mark.asyncio
async def test_get_klines_maps_to_canonical_ohlcv() -> None:
    src = GenericHttpDataSource(
        name="my-venue",
        base_url="https://api.example.com/v1",
        klines_path="/klines",
        klines_field_map={
            "open_time": "t",
            "open": "o",
            "high": "h",
            "low": "l",
            "close": "c",
            "volume": "v",
        },
        klines_array_key="data",
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return _json_response({
            "data": [
                {"t": 1, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 12.5},
                {"t": 2, "o": 101, "h": 102, "l": 100, "c": 101.5, "v": 14.0},
            ]
        })

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    import app.data_sources.generic_http as mod

    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        klines = await src.get_klines("BTCUSDT", interval="1h", limit=2)
    finally:
        mod.httpx.AsyncClient = real

    assert len(klines) == 2
    assert klines[0]["open"] == 100
    assert klines[0]["high"] == 101
    assert klines[0]["volume"] == 12.5


@pytest.mark.asyncio
async def test_get_recent_trades_returns_list() -> None:
    src = GenericHttpDataSource(
        name="my-venue",
        base_url="https://api.example.com/v1",
        trades_path="/trades",
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return _json_response([
            {"price": 100, "side": "buy", "qty": 0.5},
            {"price": 101, "side": "sell", "qty": 0.3},
        ])

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    import app.data_sources.generic_http as mod

    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        trades = await src.get_recent_trades("BTCUSDT", limit=2)
    finally:
        mod.httpx.AsyncClient = real

    assert len(trades) == 2
    assert trades[0]["price"] == 100


@pytest.mark.asyncio
async def test_request_includes_symbol_and_query() -> None:
    src = GenericHttpDataSource(
        name="my-venue",
        base_url="https://api.example.com/v1",
        ticker_path="/ticker",
    )

    captured: Dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        return _json_response({"last_price": 1})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    import app.data_sources.generic_http as mod

    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        await src.get_ticker("ETHUSDT")
    finally:
        mod.httpx.AsyncClient = real

    assert "ETHUSDT" in captured["url"]
    assert captured["url"].startswith("https://api.example.com/v1/ticker")


def test_generic_http_source_satisfies_data_source_protocol() -> None:
    """Structural conformance with DataSource — duck-typed, not runtime Protocol."""
    src = GenericHttpDataSource(name="x", base_url="http://x")
    assert hasattr(src, "name")
    assert hasattr(src, "get_ticker")
    assert hasattr(src, "get_klines")
    assert hasattr(src, "get_recent_trades")
    assert callable(src.get_ticker)
    assert callable(src.get_klines)
    assert callable(src.get_recent_trades)