"""Tests for ExchangeFactory — registration, lookup, support list."""

from __future__ import annotations

import pytest

from app.exchanges.factory import ExchangeFactory, _auto_register_exchanges


@pytest.fixture(autouse=True)
def _reset_factory():
    """Reset factory state between tests."""
    ExchangeFactory._instances.clear()
    ExchangeFactory._exchange_classes.clear()
    _auto_register_exchanges()
    yield
    ExchangeFactory._instances.clear()
    ExchangeFactory._exchange_classes.clear()
    _auto_register_exchanges()


def test_factory_lists_supported_exchanges() -> None:
    supported = ExchangeFactory.list_supported_exchanges()
    assert isinstance(supported, list)
    assert len(supported) >= 3  # at least Binance, OKX, Bitget


def test_factory_includes_three_exchanges() -> None:
    supported = ExchangeFactory.list_supported_exchanges()
    assert "binance_usdm" in supported
    assert "okx_swap" in supported
    assert "bitget_usdt_futures" in supported


def test_factory_get_or_create_returns_adapter() -> None:
    ex = ExchangeFactory.get_or_create("binance_usdm", api_key="", secret_key="", use_testnet=True)
    assert ex is not None
    assert hasattr(ex, "get_ticker")
    assert hasattr(ex, "place_order")


def test_factory_get_or_create_returns_singleton() -> None:
    e1 = ExchangeFactory.get_or_create("binance_usdm", api_key="")
    e2 = ExchangeFactory.get_or_create("binance_usdm", api_key="")
    assert e1 is e2


def test_factory_unknown_exchange_raises() -> None:
    with pytest.raises(ValueError):
        ExchangeFactory.get_or_create("totally-fake-exchange")


def test_factory_case_insensitive() -> None:
    e1 = ExchangeFactory.get_or_create("BINANCE_USDM", api_key="")
    e2 = ExchangeFactory.get_or_create("binance_usdm", api_key="")
    assert e1 is e2


def test_factory_register_exchange_class() -> None:
    class FakeExchange:
        name = "fake-exchange"

        def __init__(self, api_key="", secret_key="", passphrase="", use_testnet=True):
            self.api_key = api_key

    ExchangeFactory.register_exchange("fake", FakeExchange)
    ex = ExchangeFactory.get_or_create("fake", api_key="k")
    assert ex.api_key == "k"