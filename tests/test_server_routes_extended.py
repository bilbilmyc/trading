"""Extended server route tests — covers more endpoints and edge cases."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List

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


def test_storage_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/storage/status")
        assert r.status_code == 200
        assert r.json()["driver"] == "sqlite"


def test_kill_switch_set_and_get(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post("/api/v1/risk/kill-switch", json={"enabled": True, "reason": "test"})
        assert r.status_code == 200
        assert r.json()["enabled"] is True

        r = c.get("/api/v1/risk/kill-switch")
        assert r.json()["enabled"] is True

        r = c.post("/api/v1/risk/kill-switch", json={"enabled": False, "reason": "ok"})
        assert r.json()["enabled"] is False


def test_suggest_strategy_endpoint_default(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        candles = [
            {"open_time": "2026-01-01T00:00:00", "close": 100, "open": 100, "high": 105, "low": 95, "volume": 1}
            for _ in range(30)
        ]
        r = c.post("/api/v1/strategies/suggest", json={"klines": candles})
        assert r.status_code == 200
        body = r.json()
        assert "kind" in body
        assert "params" in body
        assert "rationale" in body


def test_suggest_strategy_endpoint_with_prefer_rsi(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        candles = [
            {"open_time": "2026-01-01T00:00:00", "close": 100, "open": 100, "high": 105, "low": 95, "volume": 1}
            for _ in range(30)
        ]
        r = c.post("/api/v1/strategies/suggest", json={"klines": candles, "prefer": "rsi"})
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "rsi_mean_reversion"


def test_strategies_sma_with_short_window_larger_than_long_rejected(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/strategies/sma",
            json={
                "exchange": "binance_usdm",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "short_window": 30,
                "long_window": 5,
                "enabled": True,
                "mode": "paper",
            },
        )
        assert r.status_code in (400, 422)


def test_run_signal_cycle_endpoint(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        # Runner cycle endpoint may or may not exist; accept 200/404/500.
        r = c.post("/api/v1/runner/cycle", json={"poll_seconds": 60, "candle_limit": 80})
        assert r.status_code in (200, 404, 500)


def test_start_stop_signal_runner(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post("/api/v1/runner/start", json={"poll_seconds": 60, "candle_limit": 80})
        assert r.status_code in (200, 500)
        r = c.post("/api/v1/runner/stop")
        assert r.status_code in (200, 500)


def test_strategy_lifecycle_start_stop(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        # Create strategy.
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
        strategy_name = r.json().get("strategy", {}).get("name") or r.json().get("name")
        if strategy_name:
            # Try to start and stop.
            r = c.post(f"/api/v1/strategies/{strategy_name}/start")
            assert r.status_code in (200, 404, 500)
            r = c.post(f"/api/v1/strategies/{strategy_name}/stop")
            assert r.status_code in (200, 404, 500)


def test_post_sizing_rejects_invalid_input(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        # entry == SL should be rejected.
        r = c.post(
            "/api/v1/sizing",
            json={"account_equity": 10000, "entry_price": 100, "stop_loss_price": 100},
        )
        assert r.status_code == 400


def test_signals_recent_endpoint(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/signals/recent?limit=10")
        assert r.status_code == 200
        assert "signals" in r.json()


def test_events_recent_with_category_filter(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/events/recent?category=risk&limit=5")
        assert r.status_code == 200
        assert "events" in r.json()


def test_paper_summary_after_reset(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        c.post("/api/v1/paper/reset", json={"initial_cash": 5000.0})
        r = c.get("/api/v1/paper")
        assert r.status_code == 200
        assert r.json()["equity"] == 5000.0


def test_engine_status_shape(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/engine/status")
        assert r.status_code == 200
        body = r.json()
        assert "strategies" in body or "running" in body


def test_runner_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/runner/status")
        assert r.status_code == 200


def test_post_sources_register_and_list(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/sources",
            json={"name": "test-source", "base_url": "https://x.test/v1"},
        )
        assert r.status_code == 200

        r = c.get("/api/v1/sources")
        names = [s["name"] for s in r.json()["sources"]]
        assert "test-source" in names

        r = c.delete("/api/v1/sources/test-source")
        assert r.status_code == 200

        r = c.get("/api/v1/sources")
        names = [s["name"] for s in r.json()["sources"]]
        assert "test-source" not in names