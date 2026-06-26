"""Tests for /api/v1/sizing endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _settings(**overrides) -> Settings:
    defaults = dict(
        sqlite_path=":memory:",
        enable_live_trading=False,
        frontend_static_dir="/tmp/static",
        llm_api_key="",
        binance_api_key="",
        binance_secret_key="",
        binance_enabled=True,
        binance_usdm_enabled=True,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_sizing_endpoint_returns_breakdown() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sizing",
            json={
                "account_equity": 10000,
                "entry_price": 100,
                "stop_loss_price": 98,
                "take_profit_price": 104,
                "leverage": 5,
                "risk_pct": 0.02,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["quantity"] == 100.0
        assert body["notional"] == 10000.0
        assert body["margin"] == 2000.0
        assert abs(body["risk_amount"] - 200.0) < 0.01
        assert body["risk_reward_ratio"] == 2.0


def test_sizing_endpoint_returns_400_on_business_logic_error() -> None:
    """Entry == SL is a runtime ValueError — caught and 400'd."""
    app = create_app(_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sizing",
            json={
                "account_equity": 10000,
                "entry_price": 100,
                "stop_loss_price": 100,  # same as entry
            },
        )
        assert response.status_code == 400


def test_sizing_endpoint_returns_422_on_pydantic_validation() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sizing",
            json={
                "account_equity": -1,  # caught by Field(gt=0) validation
                "entry_price": 100,
                "stop_loss_price": 98,
            },
        )
        assert response.status_code == 422