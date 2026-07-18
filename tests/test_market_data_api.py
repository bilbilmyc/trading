from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        sqlite_path=str(tmp_path / "trading.sqlite3"),
        market_data_catalog_path=str(tmp_path / "market_data.duckdb"),
        market_data_parquet_dir=str(tmp_path / "market_data"),
        enable_live_trading=False,
        frontend_static_dir=str(tmp_path / "static"),
        llm_api_key="",
        binance_api_key="",
        binance_secret_key="",
        binance_enabled=False,
        binance_usdm_enabled=False,
        bitget_enabled=False,
    )


def _candles() -> list[dict[str, object]]:
    prices = [100.0, 100.0, 100.0, 110.0, 120.0, 125.0]
    return [
        {
            "timestamp": f"2026-01-01T00:0{index}:00Z",
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": 100.0,
        }
        for index, price in enumerate(prices)
    ]


def test_versioned_data_backtest_is_recorded_and_reproducible(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        imported = client.post(
            "/api/v1/market-data/datasets",
            json={"symbol": "BTCUSDT", "timeframe": "1m", "source": "fixture", "candles": _candles()},
        )
        assert imported.status_code == 201
        dataset = imported.json()
        assert "parquet_path" not in dataset
        assert dataset["quality_report"]["valid"] is True

        queried = client.get(
            f"/api/v1/market-data/datasets/{dataset['version']}/candles",
            params={"start": "2026-01-01T00:02:00Z", "end": "2026-01-01T00:04:00Z"},
        )
        assert queried.status_code == 200
        assert len(queried.json()["candles"]) == 3

        backtest = client.post(
            "/api/v1/backtest",
            json={"data_version": dataset["version"], "short_window": 2, "long_window": 3},
        )
        assert backtest.status_code == 200
        result = backtest.json()
        assert result["data_version"] == dataset["version"]
        assert result["backtest_run_id"] > 0
        assert len(result["result_hash"]) == 64
        assert result["fill_history"]
        assert result["fill_history"][0]["time"].endswith("Z")

        recorded = client.get(f"/api/v1/backtests/{result['backtest_run_id']}")
        assert recorded.status_code == 200
        body = recorded.json()
        assert body["data_version"] == dataset["version"]
        assert body["strategy_parameters"] == {
            "initial_capital": 10000.0,
            "long_window": 3,
            "position_size_pct": 1.0,
            "short_window": 2,
        }
        assert body["data_start"] == "2026-01-01T00:00:00Z"
        assert body["data_end"] == "2026-01-01T00:05:00Z"

        replay = client.post(f"/api/v1/backtests/{result['backtest_run_id']}/reproduce")
        assert replay.status_code == 200
        assert replay.json()["reproducible"] is True


def test_failed_dataset_is_visible_but_blocked_from_backtest(tmp_path: Path) -> None:
    bad = _candles()
    bad[2]["high"] = 99.0
    bad[2]["low"] = 101.0
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        imported = client.post(
            "/api/v1/market-data/datasets",
            json={"symbol": "BTCUSDT", "timeframe": "1m", "source": "fixture", "candles": bad},
        )
        assert imported.status_code == 201
        dataset = imported.json()
        assert dataset["quality_report"]["valid"] is False

        response = client.post(
            "/api/v1/backtest",
            json={"data_version": dataset["version"], "short_window": 2, "long_window": 3},
        )
        assert response.status_code == 409
        assert "failed data-quality" in response.json()["detail"]
