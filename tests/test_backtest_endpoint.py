"""Tests for /api/v1/backtest endpoint."""

from __future__ import annotations

from datetime import datetime

import pytest  # noqa: F401
from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _settings() -> Settings:
    return Settings(
        sqlite_path=":memory:",
        enable_live_trading=False,
        frontend_static_dir="/tmp/static",
        llm_api_key="",
        binance_api_key="",
        binance_secret_key="",
        binance_enabled=True,
        binance_usdm_enabled=True,
    )


def _klines(prices: list) -> list:
    return [
        {
            "open_time": "2026-01-01T00:00:00",
            "open": p,
            "high": p + 1,
            "low": p - 1,
            "close": p,
            "volume": 1.0,
        }
        for p in prices
    ]


def test_backtest_endpoint_runs_against_supplied_klines() -> None:
    """Backtest takes klines inline (no exchange call needed) — proves data-source-free."""
    app = create_app(_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/backtest",
            json={
                "klines": _klines([100] * 6 + [102, 105, 108, 110, 109, 107, 105, 100]),
                "short_window": 2,
                "long_window": 4,
                "initial_capital": 10_000,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["initial_capital"] == 10_000
        assert "equity_curve" in body
        assert "total_pnl" in body


def test_backtest_endpoint_400_on_empty_klines() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        # Empty list is rejected by pydantic at 422.
        response = client.post(
            "/api/v1/backtest",
            json={"klines": [], "short_window": 5, "long_window": 20, "initial_capital": 10_000},
        )
        assert response.status_code == 422