"""Tests for /api/v1/backtest endpoint."""

from __future__ import annotations

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


def test_backtest_endpoint_exposes_execution_assumptions_and_trade_history() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/backtest",
            json={
                "klines": _klines([100, 100, 100, 110, 120, 125]),
                "short_window": 2,
                "long_window": 3,
                "initial_capital": 1_000,
                "fee_rate": 0.002,
                "slippage_rate": 0.001,
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_fees"] > 0
    assert "gross_pnl" in body
    assert "total_return_pct" in body
    assert "profit_factor" in body
    assert isinstance(body["trade_history"], list)


def test_backtest_endpoint_rejects_invalid_execution_rate() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/backtest",
            json={
                "klines": _klines([100, 100, 100, 110]),
                "short_window": 2,
                "long_window": 3,
                "fee_rate": 1.0,
            },
        )

    assert response.status_code == 422
