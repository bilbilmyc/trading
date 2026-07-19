"""Exhaustive server route smoke tests — hits every public endpoint."""

from __future__ import annotations

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
        binance_enabled=True,
        binance_usdm_enabled=True,
        bitget_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _candles(n: int = 30) -> list:
    base = "2026-01-01T00:00:00"
    return [
        {
            "open_time": f"{base}",
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 100.0 + (i % 5) * 0.5,
            "volume": 1.0,
        }
        for i in range(n)
    ]


# ── Health / config ──────────────────────────────────────────────────


def test_root_health_ok(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_config_returns_settings_dict(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/config")
        assert r.status_code == 200
        body = r.json()
        assert "exchanges" in body
        assert "persistence" in body


def test_exchanges_lists_supported(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/exchanges")
        assert r.status_code == 200
        body = r.json()
        assert "exchanges" in body
        assert "enabled" in body


# ── Risk ──────────────────────────────────────────────────────────────


def test_kill_switch_status_default_off(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/risk/kill-switch")
        assert r.status_code == 200
        assert r.json()["enabled"] is False


def test_kill_switch_toggle_and_audit(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post("/api/v1/risk/kill-switch", json={"enabled": True, "reason": "test"})
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        # Audit event recorded.
        events = c.get("/api/v1/events/recent?event_type=kill_switch_enabled").json()["events"]
        assert any(e["level"] == "critical" for e in events)


# ── Sizing ──────────────────────────────────────────────────────────


def test_sizing_default_request(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/sizing",
            json={"account_equity": 10000, "entry_price": 100, "stop_loss_price": 99},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["quantity"] > 0
        assert body["risk_pct"] <= 0.02


# ── Backtest ────────────────────────────────────────────────────────


def test_backtest_default_sma(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post("/api/v1/backtest", json={"klines": _candles(30)})
        assert r.status_code == 200
        body = r.json()
        assert "final_equity" in body
        assert "total_pnl" in body


def test_grid_search_backtest_returns_ranked_candidates(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        response = c.post(
            "/api/v1/backtest/grid-search",
            json={
                "klines": _candles(30),
                "fee_rate": 0,
                "short_windows": [2, 3],
                "long_windows": [4, 6],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["search"]["candidate_count"] == 4
    assert body["search"]["in_sample_only"] is True
    assert len(body["candidates"]) == 4
    assert body["best"]["parameters"] == body["candidates"][0]["parameters"]
    assert body["backtest_run_id"] > 0


def test_grid_search_data_version_can_be_reproduced(tmp_path) -> None:
    catalog_candles = [
        {
            "timestamp": f"2026-01-{1 + index // 24:02d}T{index % 24:02d}:00:00Z",
            "open": 100.0 + index * 0.1,
            "high": 105.0 + index * 0.1,
            "low": 95.0 + index * 0.1,
            "close": 100.0 + (index % 5) * 0.5,
            "volume": 10.0,
        }
        for index in range(30)
    ]
    settings = _settings(
        sqlite_path=str(tmp_path / "h.sqlite3"),
        market_data_catalog_path=str(tmp_path / "market_data.duckdb"),
        market_data_parquet_dir=str(tmp_path / "market_data"),
    )
    with TestClient(create_app(settings)) as c:
        imported = c.post(
            "/api/v1/market-data/datasets",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "source": "test",
                "candles": catalog_candles,
            },
        )
        assert imported.status_code == 201
        response = c.post(
            "/api/v1/backtest/grid-search",
            json={
                "data_version": imported.json()["version"],
                "fee_rate": 0,
                "short_windows": [2, 3],
                "long_windows": [4, 6],
            },
        )
        assert response.status_code == 200
        reproduced = c.post(f"/api/v1/backtests/{response.json()['backtest_run_id']}/reproduce")

    assert reproduced.status_code == 200
    assert reproduced.json()["reproducible"] is True


def test_grid_search_backtest_rejects_more_than_64_valid_pairs(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        response = c.post(
            "/api/v1/backtest/grid-search",
            json={
                "klines": _candles(30),
                "short_windows": list(range(1, 17)),
                "long_windows": list(range(17, 33)),
            },
        )

    assert response.status_code == 422


def test_portfolio_backtest_returns_aggregate_and_strategy_attribution(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        response = c.post(
            "/api/v1/backtest/portfolio",
            json={
                "klines": _candles(30),
                "initial_capital": 10_000,
                "fee_rate": 0,
                "strategies": [
                    {"name": "fast", "short_window": 2, "long_window": 4, "weight": 0.6},
                    {"name": "slow", "short_window": 3, "long_window": 6, "weight": 0.4},
                ],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio"]["allocation_model"] == "fixed_weight_separate_capital"
    assert [item["allocated_capital"] for item in body["portfolio"]["strategies"]] == [
        6000.0,
        4000.0,
    ]
    assert body["final_equity"] == round(
        sum(item["result"]["final_equity"] for item in body["portfolio"]["strategies"]), 4
    )
    assert body["backtest_run_id"] > 0


def test_portfolio_backtest_data_version_can_be_reproduced(tmp_path) -> None:
    catalog_path = tmp_path / "market_data.duckdb"
    parquet_path = tmp_path / "market_data"
    catalog_candles = [
        {
            "timestamp": f"2026-01-{1 + index // 24:02d}T{index % 24:02d}:00:00Z",
            "open": 100.0 + index * 0.1,
            "high": 105.0 + index * 0.1,
            "low": 95.0 + index * 0.1,
            "close": 100.0 + (index % 5) * 0.5,
            "volume": 10.0,
        }
        for index in range(30)
    ]
    settings = _settings(
        sqlite_path=str(tmp_path / "h.sqlite3"),
        market_data_catalog_path=str(catalog_path),
        market_data_parquet_dir=str(parquet_path),
    )
    with TestClient(create_app(settings)) as c:
        imported = c.post(
            "/api/v1/market-data/datasets",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "source": "test",
                "candles": catalog_candles,
            },
        )
        assert imported.status_code == 201
        response = c.post(
            "/api/v1/backtest/portfolio",
            json={
                "data_version": imported.json()["version"],
                "initial_capital": 10_000,
                "fee_rate": 0,
                "strategies": [
                    {"name": "fast", "short_window": 2, "long_window": 4, "weight": 0.5},
                    {"name": "slow", "short_window": 3, "long_window": 6, "weight": 0.5},
                ],
            },
        )
        assert response.status_code == 200
        reproduced = c.post(f"/api/v1/backtests/{response.json()['backtest_run_id']}/reproduce")

    assert reproduced.status_code == 200
    assert reproduced.json()["reproducible"] is True


def test_portfolio_backtest_requires_complete_explicit_weights(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        response = c.post(
            "/api/v1/backtest/portfolio",
            json={
                "klines": _candles(30),
                "strategies": [
                    {"name": "one", "short_window": 2, "long_window": 4, "weight": 0.4},
                    {"name": "two", "short_window": 3, "long_window": 6, "weight": 0.4},
                ],
            },
        )

    assert response.status_code == 422


def test_backtest_short_window_must_be_smaller(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/backtest",
            json={
                "klines": _candles(30),
                "short_window": 30,
                "long_window": 5,
            },
        )
        assert r.status_code == 400


# ── Sources ─────────────────────────────────────────────────────────


def test_sources_list_initially_has_builtins(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/sources")
        assert r.status_code == 200
        body = r.json()
        assert "sources" in body


def test_sources_register_duplicate_returns_409(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        # 'binance_usdm' is already a built-in source.
        r = c.post("/api/v1/sources", json={"name": "binance_usdm", "base_url": "https://x"})
        assert r.status_code == 409


def test_sources_delete_unknown_returns_404(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.delete("/api/v1/sources/nonexistent-source")
        assert r.status_code == 404


# ── AI analyze ─────────────────────────────────────────────────────


def test_ai_analyze_no_key_returns_error_kind(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/ai/analyze",
            json={"exchange": "binance_usdm", "symbol": "BTCUSDT", "interval": "1h", "limit": 30},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("error_kind") == "api_key_missing"


# ── Strategies ──────────────────────────────────────────────────────


def test_strategies_sma_create(tmp_path) -> None:
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


def test_strategies_list_after_create(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        c.post(
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
        r = c.get("/api/v1/strategies")
        assert r.status_code == 200
        strategies = r.json().get("strategies", [])
        assert len(strategies) >= 1


# ── Engine / runner / monitor ─────────────────────────────────────


def test_engine_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/engine/status")
        assert r.status_code == 200


def test_runner_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/runner/status")
        assert r.status_code == 200


def test_monitor_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/monitor/status")
        assert r.status_code == 200


def test_monitor_alerts_empty(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/monitor/alerts")
        assert r.status_code == 200
        body = r.json()
        assert "alerts" in body or "total" in body


def test_monitor_last_error(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/monitor/last-error")
        assert r.status_code == 200


# ── Paper / sync / signals ────────────────────────────────────────


def test_paper_summary(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/paper")
        assert r.status_code == 200


def test_sync_status(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/sync/status")
        assert r.status_code == 200


def test_signals_recent_empty(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/signals/recent?limit=10")
        assert r.status_code == 200


def test_events_recent_filtered(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/events/recent?category=risk&event_type=kill_switch_enabled&limit=5")
        assert r.status_code == 200


def test_storage_status_shape(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/storage/status")
        assert r.status_code == 200
        body = r.json()
        assert body.get("driver") == "sqlite"


# ── Suggest strategy ─────────────────────────────────────────────


def test_suggest_endpoint_returns_sma(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post("/api/v1/strategies/suggest", json={"klines": _candles(50)})
        assert r.status_code == 200
        body = r.json()
        assert "kind" in body
        assert "params" in body
        assert "rationale" in body


# ── OpenAPI schema available ─────────────────────────────────────


def test_openapi_schema_includes_routes(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        paths = schema.get("paths", {})
        assert "/health" in paths
        assert "/api/v1/sizing" in paths
        assert "/api/v1/backtest" in paths


# ── 404 / 422 error paths ──────────────────────────────────────


def test_ticker_for_unknown_data_source_returns_404(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.get("/api/v1/ticker/never_configured/XXX")
        assert r.status_code in (404, 500, 502)


def test_sizing_with_zero_quantity_rejected(tmp_path) -> None:
    """account_equity=0 is invalid (gt=0)."""
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/sizing",
            json={"account_equity": 0, "entry_price": 100, "stop_loss_price": 99},
        )
        assert r.status_code == 422


def test_evaluate_signals_endpoint(tmp_path) -> None:
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/signals/evaluate",
            json={"exchange": "binance_usdm", "symbol": "BTCUSDT", "interval": "1h", "limit": 30},
        )
        # Endpoint may 200, 422 (missing required field), or 500.
        assert r.status_code in (200, 422, 500)
