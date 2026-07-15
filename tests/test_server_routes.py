"""Comprehensive route smoke tests — hit every endpoint in app/api/server.py."""

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
        okx_enabled=False,
        binance_enabled=False,
        binance_usdm_enabled=True,
        bitget_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_root_health(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_cors_allows_current_vite_development_origin(tmp_path) -> None:
    """The configured Vite port must remain usable for local browser requests."""
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        response = c.get("/health", headers={"Origin": "http://localhost:5180"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5180"


def test_cors_does_not_allow_the_retired_vite_port(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        response = c.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_get_venues(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/health/venues")
        assert r.status_code == 200
        # Returns a dict keyed by venue name.
        assert isinstance(r.json(), dict)


def test_get_config(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/config")
        assert r.status_code == 200
        # Config shape: app_name, exchanges, etc.
        assert "app_name" in r.json() or "app_env" in r.json()


def test_get_exchanges(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/exchanges")
        assert r.status_code == 200
        assert "exchanges" in r.json()


def test_get_kill_switch_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/risk/kill-switch")
        assert r.status_code == 200
        assert r.json()["enabled"] is False


def test_get_recent_events(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/events/recent?limit=10")
        assert r.status_code == 200
        assert "events" in r.json()


def test_get_recent_signals(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/signals/recent?limit=10")
        assert r.status_code == 200
        assert "signals" in r.json()


def test_list_strategies_empty(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/strategies")
        assert r.status_code == 200


def test_get_paper_summary(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/paper")
        assert r.status_code == 200
        assert "equity" in r.json()


def test_post_paper_reset(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post("/api/v1/paper/reset", json={"initial_cash": 10000.0})
        assert r.status_code == 200


def test_get_sync_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/sync/status")
        assert r.status_code == 200
        assert "order_sync" in r.json()
        assert "position_sync" in r.json()


def test_get_monitor_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/monitor/status")
        assert r.status_code == 200


def test_get_monitor_alerts(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/monitor/alerts")
        assert r.status_code == 200


def test_get_monitor_last_error(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/monitor/last-error")
        assert r.status_code == 200


def test_get_engine_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/engine/status")
        assert r.status_code == 200


def test_get_runner_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/runner/status")
        assert r.status_code == 200


def test_get_strategies_sma_create(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/strategies/sma",
            json={
                "exchange": "binance_usdm",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "short_window": 5,
                "long_window": 20,
                "enabled": True,
                "mode": "paper",
            },
        )
        assert r.status_code == 200
        # Returns the auto-generated strategy info.
        body = r.json()
        assert "strategy" in body


def test_get_strategies_sma_default(tmp_path) -> None:
    """Without name, server uses auto-generated SMA strategy."""
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/strategies/sma",
            json={
                "exchange": "binance_usdm",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "short_window": 5,
                "long_window": 20,
                "enabled": True,
                "mode": "paper",
            },
        )
        assert r.status_code == 200


def test_get_sizing_endpoint(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/sizing",
            json={
                "account_equity": 10000,
                "entry_price": 100,
                "stop_loss_price": 98,
                "leverage": 5,
                "risk_pct": 0.02,
            },
        )
        assert r.status_code == 200
        assert r.json()["quantity"] == 100.0


def test_get_backtest_endpoint(tmp_path) -> None:
    candles = [
        {"open_time": "2026-01-01T00:00:00", "open": 100, "high": 105, "low": 95, "close": 100, "volume": 1}
        for _ in range(30)
    ]
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/backtest",
            json={"klines": candles, "short_window": 3, "long_window": 7, "initial_capital": 10_000},
        )
        assert r.status_code == 200
        assert "final_equity" in r.json()


def test_list_sources_empty(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/sources")
        assert r.status_code == 200
        assert "sources" in r.json()


def test_ai_analyze_without_key_returns_api_key_missing(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/ai/analyze",
            json={"exchange": "binance_usdm", "symbol": "BTCUSDT", "interval": "1h", "limit": 30},
        )
        assert r.status_code == 200
        assert r.json()["error_kind"] == "api_key_missing"
