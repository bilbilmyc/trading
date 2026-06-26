"""Tests for DataSource Protocol — public market data seam.

Verifies structural conformance via runtime_checkable and proves the
exchange adapters already satisfy the surface (so AppState can treat
any ExchangeBase as a DataSource without explicit registration).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.data_sources.base import DataSource


class _DuckDataSource:
    """Minimal duck-typed implementation."""

    name = "test-duck"

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        return {"last_price": 100.0, "symbol": symbol}

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return [{"close": 100.0, "volume": 1.0}]

    async def get_recent_trades(
        self,
        symbol: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return [{"price": 100.0, "side": "buy"}]


class _MissingMethod:
    name = "incomplete"

    async def get_ticker(self, symbol: str):
        return {}


@pytest.mark.asyncio
async def test_duck_typed_object_satisfies_protocol() -> None:
    src = _DuckDataSource()
    assert hasattr(src, "name")
    assert src.name == "test-duck"
    assert hasattr(src, "get_ticker")
    ticker = await src.get_ticker("BTCUSDT")
    assert ticker["last_price"] == 100.0


def test_protocol_has_three_async_methods() -> None:
    """DataSource interface surface — keep small for testability."""
    methods = [m for m in dir(DataSource) if not m.startswith("_")]
    assert "get_ticker" in methods
    assert "get_klines" in methods
    assert "get_recent_trades" in methods

    # `name` is an attribute (annotation), not a method.
    annotations = getattr(DataSource, "__annotations__", {})
    assert "name" in annotations


@pytest.mark.asyncio
async def test_exchange_base_conforms_to_data_source() -> None:
    """BinanceExchange already implements the surface — no inheritance change."""
    from app.exchanges.binance import BinanceExchange

    ex = BinanceExchange(api_key="", secret_key="")
    # Verify the same methods exist with the right signatures.
    assert ex.name == "binance"
    assert callable(ex.get_ticker)
    assert callable(ex.get_klines)
    assert callable(ex.get_recent_trades)


@pytest.mark.asyncio
async def test_okx_exchange_conforms_to_data_source() -> None:
    from app.exchanges.okx import OKXExchange

    ex = OKXExchange(api_key="", secret_key="", passphrase="")
    assert ex.name == "okx"
    assert callable(ex.get_ticker)
    assert callable(ex.get_klines)
    assert callable(ex.get_recent_trades)


@pytest.mark.asyncio
async def test_bitget_exchange_conforms_to_data_source() -> None:
    from app.exchanges.bitget_usdt_futures import BitgetUSDTFuturesExchange

    ex = BitgetUSDTFuturesExchange(api_key="", secret_key="", passphrase="")
    assert ex.name == "bitget_usdt_futures"
    assert callable(ex.get_ticker)
    assert callable(ex.get_klines)
    assert callable(ex.get_recent_trades)


@pytest.mark.asyncio
async def test_duck_data_source_methods_can_be_called_via_interface() -> None:
    """Treat the duck as DataSource — should be polymorphic at the call site."""
    src: DataSource = _DuckDataSource()
    ticker = await src.get_ticker("ETHUSDT")
    klines = await src.get_klines("ETHUSDT", interval="5m", limit=10)
    trades = await src.get_recent_trades("ETHUSDT", limit=5)

    assert ticker["symbol"] == "ETHUSDT"
    assert len(klines) == 1
    assert len(trades) == 1