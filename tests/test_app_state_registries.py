"""Tests for AppState's data_sources and trading_exchanges registries.

Public market data should be reachable even when no exchange API keys
are configured. Trading exchanges are only registered when keys + the
global enable_live_trading flag are both set.
"""

from __future__ import annotations

import pytest

from app.api.server import AppState, create_app
from config import Settings


def _settings(**overrides) -> Settings:
    defaults = dict(
        sqlite_path=":memory:",
        enable_live_trading=False,
        frontend_static_dir="/tmp/static",
        okx_api_key="",
        okx_secret_key="",
        okx_passphrase="",
        okx_enabled=False,
        okx_swap_enabled=False,
        binance_api_key="",
        binance_secret_key="",
        binance_enabled=False,
        binance_usdm_enabled=False,
        bitget_api_key="",
        bitget_secret_key="",
        bitget_passphrase="",
        bitget_enabled=False,
        bitget_usdt_futures_enabled=False,
        llm_api_key="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_no_keys_no_trading_exchanges_in_app_state() -> None:
    state = AppState(_settings())
    assert state.trading_exchanges == {}


def test_no_keys_no_live_trading_flag_skips_trading_registration() -> None:
    """Even if API keys are present, ENABLE_LIVE_TRADING must be true."""
    settings = _settings(
        binance_api_key="k",
        binance_secret_key="s",
        binance_enabled=True,
        binance_usdm_enabled=True,
        enable_live_trading=False,
    )
    state = AppState(settings)
    assert state.trading_exchanges == {}


def test_keys_and_flag_register_trading_exchange() -> None:
    settings = _settings(
        binance_api_key="k",
        binance_secret_key="s",
        binance_enabled=True,
        binance_usdm_enabled=True,
        enable_live_trading=True,
    )
    state = AppState(settings)
    assert any(name.startswith("binance") for name in state.trading_exchanges)


def test_disabled_exchange_not_registered_as_trading() -> None:
    settings = _settings(
        okx_api_key="k",
        okx_secret_key="s",
        okx_passphrase="p",
        okx_enabled=False,
        okx_swap_enabled=False,
        enable_live_trading=True,
    )
    state = AppState(settings)
    assert "okx" not in state.trading_exchanges
    assert "okx_swap" not in state.trading_exchanges


def test_app_boots_cleanly_with_zero_configuration() -> None:
    """Full FastAPI app boots, /health returns 200, even with no keys."""
    app = create_app(_settings())
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"