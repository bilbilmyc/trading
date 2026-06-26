"""Tests for ExchangeBase abstract methods + ContractExchangeBase helper."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.exchanges.base import ExchangeBase
from app.exchanges.contract_base import ContractExchangeBase


class _StubBase(ExchangeBase):
    """Minimal subclass of ExchangeBase for testing the abstract methods."""

    def __init__(self):
        super().__init__()
        self._ticker_calls: List[str] = []
        self._klines_calls: List[str] = []
        self._trades_calls: List[str] = []

    @property
    def name(self) -> str:
        return "stub"

    @property
    def base_url(self) -> str:
        return "https://stub.local/v1"

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        self._ticker_calls.append(symbol)
        return {"last_price": 100.0, "symbol": symbol}

    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 100) -> List[Dict[str, Any]]:
        self._klines_calls.append(f"{symbol}:{interval}:{limit}")
        return [{"close": 100.0, "volume": 1.0}]

    async def get_recent_trades(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        self._trades_calls.append(f"{symbol}:{limit}")
        return [{"price": 100.0, "side": "buy"}]

    async def get_account_balance(self) -> Dict[str, Any]:
        return {"USDT": {"free": 1000, "locked": 0}}

    async def place_order(self, symbol: str, side: str, order_type: str, quantity: float, price=None) -> Dict[str, Any]:
        return {"order_id": "stub-1", "status": "filled"}

    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return {"cancelled": True}

    async def get_open_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        return []

    async def cancel_all_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        return []

    async def get_available_balances(self) -> Dict[str, Any]:
        return {"USDT": {"free": 1000, "locked": 0}}

    async def get_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return {"order_id": order_id, "status": "filled"}

    async def subscribe_ticker(self, symbol: str, callback=None) -> None:
        pass

    async def unsubscribe_ticker(self, symbol: str) -> None:
        pass


class _StubContract(_StubBase, ContractExchangeBase):
    async def get_contract_markets(self, quote_asset: str = "USDT", search=None, limit: int = 200):
        return []

    async def get_fee_rate(self, symbol: str):
        return {"maker": 0.0002, "taker": 0.0005}

    async def get_positions(self, symbol: str = None):
        return []

    async def place_contract_order(self, **kwargs):
        return {"order_id": "c-1", "status": "filled"}

    async def set_leverage(self, symbol: str, leverage: int):
        return {"leverage": leverage}


def test_exchange_base_initialized_at_is_set() -> None:
    from datetime import datetime

    e = _StubBase()
    # Init timestamp set in __init__.
    assert isinstance(e._initialized_at, datetime)


def test_exchange_base_default_testnet_true() -> None:
    """ExchangeBase default use_testnet=True."""
    e = _StubBase()
    assert e.use_testnet is True


def test_exchange_base_default_keys_empty() -> None:
    e = _StubBase()
    assert e.api_key == ""
    assert e.secret_key == ""
    assert e.passphrase == ""


def test_exchange_base_close_is_noop() -> None:
    import asyncio

    e = _StubBase()
    asyncio.run(e.close())


@pytest.mark.asyncio
async def test_stub_get_ticker_returns_dict() -> None:
    e = _StubBase()
    t = await e.get_ticker("BTCUSDT")
    assert t["last_price"] == 100.0
    assert "BTCUSDT" in e._ticker_calls


@pytest.mark.asyncio
async def test_stub_get_klines_returns_list() -> None:
    e = _StubBase()
    k = await e.get_klines("ETHUSDT", interval="5m", limit=20)
    assert isinstance(k, list)
    assert any("ETHUSDT:5m:20" in c for c in e._klines_calls)


@pytest.mark.asyncio
async def test_stub_get_recent_trades_returns_list() -> None:
    e = _StubBase()
    t = await e.get_recent_trades("BTCUSDT", limit=10)
    assert isinstance(t, list)


@pytest.mark.asyncio
async def test_contract_base_concrete_subclass() -> None:
    e = _StubContract()
    assert isinstance(e, ContractExchangeBase)
    assert isinstance(e, ExchangeBase)


def test_contract_exchange_base_has_resolve_order_intent() -> None:
    assert hasattr(ContractExchangeBase, "resolve_order_intent")