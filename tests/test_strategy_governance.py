"""Strategy governance: immutable versions, WFO OOS evidence and paper review safety."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.server import create_app
from app.core.sqlite_store import SQLiteStore
from app.engine.strategy_governance import SMAParameters, run_walk_forward_backtest
from app.engine.trader import TradingEngine
from app.strategies.sma import SMAStrategy
from config import Settings


def _candles(prices: list[float]) -> list[dict[str, float | str]]:
    return [
        {
            "open_time": f"2026-01-01T00:{index:02d}:00",
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": 1.0,
        }
        for index, price in enumerate(prices)
    ]


def _settings(tmp_path) -> Settings:
    return Settings(
        sqlite_path=str(tmp_path / "governance.sqlite3"),
        market_data_catalog_path=str(tmp_path / "market_data.duckdb"),
        market_data_parquet_dir=str(tmp_path / "market_data"),
        enable_live_trading=False,
        frontend_static_dir=str(tmp_path / "static"),
        llm_api_key="",
        binance_api_key="",
        binance_secret_key="",
        binance_enabled=True,
        binance_usdm_enabled=True,
    )


def _register(engine: TradingEngine, name: str = "sma_governed") -> None:
    engine.add_strategy(
        name,
        SMAStrategy(short_window=2, long_window=4),
        exchange="binance_usdm",
        symbol="BTCUSDT",
        interval="1h",
        mode="paper",
    )


def test_engine_persists_immutable_deduplicated_strategy_versions() -> None:
    store = SQLiteStore(":memory:")
    engine = TradingEngine(store=store)
    _register(engine)

    versions = store.strategy_versions("sma_governed")
    assert [item["version"] for item in versions] == [1]

    # A no-op persistence is not a new strategy definition.
    engine._persist_strategy("sma_governed")
    assert len(store.strategy_versions("sma_governed")) == 1

    engine.set_strategy_mode("sma_governed", "signal")
    versions = store.strategy_versions("sma_governed")
    assert [item["version"] for item in versions] == [2, 1]
    assert versions[0]["mode"] == "signal"


def test_walk_forward_uses_only_out_of_sample_folds() -> None:
    prices = [100 + ((index % 9) - 4) * 2 + index * 0.25 for index in range(90)]
    result = run_walk_forward_backtest(
        _candles(prices),
        train_size=30,
        test_size=15,
        step_size=15,
        candidate_parameters=[SMAParameters(2, 4), SMAParameters(3, 6)],
        fee_rate=0.0,
    )

    assert len(result.folds) == 4
    assert result.folds[0].train_end < result.folds[0].test_start
    assert result.folds[0].test_end == 44
    assert 0 <= result.profitable_fold_ratio <= 1
    assert result.trades == sum(fold.out_of_sample.trades for fold in result.folds)
    assert "equity_curve" not in result.folds[0].as_dict()["out_of_sample"]


def test_walk_forward_audits_normalized_candidate_selection_stability() -> None:
    prices = [100 + ((index % 11) - 5) * 1.5 + index * 0.2 for index in range(90)]
    result = run_walk_forward_backtest(
        _candles(prices),
        train_size=30,
        test_size=15,
        step_size=15,
        candidate_parameters=[
            SMAParameters(3, 6),
            SMAParameters(2, 4),
            SMAParameters(2, 4),
        ],
        fee_rate=0.0,
    )

    payload = result.as_dict()
    optimization = payload["optimization"]
    assert result.candidate_count == 2
    assert optimization["candidate_count"] == 2
    assert optimization["selection_metric"][-2:] == ["short_window_asc", "long_window_asc"]
    assert sum(
        item["selected_folds"] for item in optimization["parameter_selection_frequency"]
    ) == len(result.folds)
    assert (
        optimization["parameter_stability_ratio"]
        == optimization["parameter_selection_frequency"][0]["selected_fold_ratio"]
    )


def test_walk_forward_endpoint_records_versioned_oos_evidence(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _register(app.state.trading.engine)
        response = client.post(
            "/api/v1/strategies/sma_governed/backtests/walk-forward",
            json={
                "klines": _candles([100 + ((index % 7) - 3) * 2 for index in range(70)]),
                "train_size": 30,
                "test_size": 15,
                "step_size": 15,
                "candidate_parameters": [
                    {"short_window": 2, "long_window": 4},
                    {"short_window": 3, "long_window": 6},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["strategy_version"] == 1
        assert body["result"]["folds"]
        assert body["result"]["optimization"]["candidate_count"] == 2
        assert "live_mode_changed" not in body

        history = client.get("/api/v1/strategies/sma_governed/backtests")
        assert history.status_code == 200
        assert history.json()["runs"][0]["kind"] == "walk_forward"


def test_walk_forward_endpoint_accepts_versioned_market_data(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    catalog_candles = [
        {
            "timestamp": f"2026-01-{1 + index // 24:02d}T{index % 24:02d}:00:00Z",
            "open": 100.0 + index * 0.1,
            "high": 105.0 + index * 0.1,
            "low": 95.0 + index * 0.1,
            "close": 100.0 + index * 0.1,
            "volume": 10.0,
        }
        for index in range(70)
    ]
    with TestClient(app) as client:
        _register(app.state.trading.engine)
        imported = client.post(
            "/api/v1/market-data/datasets",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "source": "fixture",
                "candles": catalog_candles,
            },
        )
        assert imported.status_code == 201, imported.text

        response = client.post(
            "/api/v1/strategies/sma_governed/backtests/walk-forward",
            json={
                "data_version": imported.json()["version"],
                "train_size": 30,
                "test_size": 15,
                "step_size": 15,
                "candidate_parameters": [{"short_window": 2, "long_window": 4}],
                "fee_rate": 0,
            },
        )
        assert response.status_code == 200, response.text
        history = client.get("/api/v1/strategies/sma_governed/backtests")

    assert history.status_code == 200
    assert history.json()["runs"][0]["request"]["data_version"] == imported.json()["version"]


def test_walk_forward_endpoint_rejects_invalid_or_duplicate_candidates(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _register(app.state.trading.engine)
        response = client.post(
            "/api/v1/strategies/sma_governed/backtests/walk-forward",
            json={
                "klines": _candles([100 + index for index in range(50)]),
                "train_size": 30,
                "test_size": 15,
                "candidate_parameters": [
                    {"short_window": 2, "long_window": 4},
                    {"short_window": 2, "long_window": 4},
                ],
            },
        )
    assert response.status_code == 422


def _paper_order(order_id: str, pnl: float) -> dict[str, object]:
    return {
        "order_id": order_id,
        "exchange": "binance_usdm",
        "strategy": "sma_governed",
        "symbol": "BTCUSDT",
        "side": "sell",
        "quantity": 1.0,
        "price": 100.0,
        "fee": 0.0,
        "realized_pnl": pnl,
        "status": "filled",
        "timestamp": f"2026-01-02T00:00:{order_id[-2:]}",
        "signal_metadata": {},
    }


def test_paper_promotion_needs_manual_decision_and_never_enables_live(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        state = app.state.trading
        _register(state.engine)
        state.store.save_paper_order(_paper_order("paper-01", 12.0))
        state.store.save_paper_order(_paper_order("paper-02", 8.0))

        evaluate = client.post(
            "/api/v1/strategies/sma_governed/promotion/evaluate",
            json={
                "min_closed_trades": 2,
                "min_win_rate": 0.5,
                "min_profit_factor": 1.01,
                "min_total_pnl": 1,
            },
        )
        assert evaluate.status_code == 200, evaluate.text
        review = evaluate.json()["review"]
        assert review["status"] == "eligible"
        assert evaluate.json()["live_mode_changed"] is False
        governed = next(
            item for item in state.engine.list_strategies() if item["name"] == "sma_governed"
        )
        assert governed["mode"] == "paper"

        decision = client.post(
            f"/api/v1/strategies/sma_governed/promotion/{review['id']}/decision",
            json={"approved": True, "decided_by": "risk-owner", "note": "paper evidence reviewed"},
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()["review"]["status"] == "approved"
        assert decision.json()["live_mode_changed"] is False
        governed = next(
            item for item in state.engine.list_strategies() if item["name"] == "sma_governed"
        )
        assert governed["mode"] == "paper"
