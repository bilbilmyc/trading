"""Tests for build_engine() — only registers exchanges with API keys.

Public data sources work without keys. Trading exchanges require keys +
ENABLE_LIVE_TRADING=true. This keeps the app bootable with zero config
for users who only want data analysis queries.
"""

from __future__ import annotations

import pytest

from main import build_engine
from config import Settings


def _settings(**overrides) -> Settings:
    """Build Settings with empty API keys by default."""
    defaults = dict(
        sqlite_path=":memory:",
        enable_live_trading=False,
        # All exchange keys explicitly empty
        okx_api_key="",
        okx_secret_key="",
        okx_passphrase="",
        okx_enabled=False,
        binance_api_key="",
        binance_secret_key="",
        binance_enabled=False,
        bitget_api_key="",
        bitget_secret_key="",
        bitget_passphrase="",
        bitget_enabled=False,
        llm_api_key="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_no_keys_no_live_trading_registers_no_exchanges() -> None:
    settings = _settings()
    engine = build_engine(settings)
    assert engine._exchanges == {}, (
        f"expected no exchanges, got {list(engine._exchanges.keys())}"
    )


def test_keys_present_but_live_trading_disabled_registers_no_exchanges() -> None:
    """Even with API keys set, trading exchanges need ENABLE_LIVE_TRADING=true."""
    settings = _settings(
        binance_api_key="k",
        binance_secret_key="s",
        binance_enabled=True,
        enable_live_trading=False,
    )
    engine = build_engine(settings)
    assert engine._exchanges == {}


def test_keys_present_and_live_trading_enabled_registers_that_exchange() -> None:
    settings = _settings(
        binance_api_key="k",
        binance_secret_key="s",
        binance_enabled=True,
        enable_live_trading=True,
    )
    engine = build_engine(settings)
    assert "binance_usdm" in engine._exchanges or "binance" in engine._exchanges


def test_disabled_exchange_not_registered_even_with_keys() -> None:
    settings = _settings(
        okx_api_key="k",
        okx_secret_key="s",
        okx_passphrase="p",
        okx_enabled=False,  # explicitly disabled
        okx_swap_enabled=False,
        enable_live_trading=True,
    )
    engine = build_engine(settings)
    assert "okx" not in engine._exchanges
    assert "okx_swap" not in engine._exchanges


def test_sma_strategy_registered_independently_of_exchanges() -> None:
    """Strategies don't depend on exchange configuration."""
    settings = _settings()
    engine = build_engine(settings)
    assert "sma" in engine._strategies