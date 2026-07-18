"""Contract tests for the persisted LLM operational-insights endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                sqlite_path=str(tmp_path / "llm_insights.sqlite3"),
                frontend_static_dir=str(tmp_path / "static"),
            )
        )
    )


def _append_llm_event(
    store, *, timestamp: str, details: dict, symbol: str | None = None
) -> None:
    store.append_event(
        {
            "category": "llm",
            "event_type": "llm_decision",
            "level": "warning" if details.get("failed") else "info",
            "message": "LLM audit event",
            "details": details,
            "symbol": symbol,
            "timestamp": timestamp,
        }
    )


def test_llm_insights_empty_window(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/v1/ai/insights?minutes=60")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window_minutes"] == 60
    assert body["generated_at"]
    assert body["event_limit"] == 2000
    assert body["calls_total"] == 0
    assert body["successful_calls"] == 0
    assert body["failed_calls"] == 0
    assert body["safety_rejections"] == 0
    assert body["success_rate"] == 0
    assert body["prompt_tokens"] == 0
    assert body["completion_tokens"] == 0
    assert body["total_tokens"] == 0
    assert body["avg_latency_ms"] == 0
    assert body["p95_latency_ms"] == 0
    assert body["decisions"] == {"buy": 0, "sell": 0, "hold": 0}
    assert body["failures"] == {}
    assert body["models"] == []


def test_llm_insights_aggregates_models_failures_tokens_and_latency(tmp_path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.trading.store
        now = datetime.utcnow()
        _append_llm_event(
            store,
            timestamp=(now - timedelta(minutes=8)).isoformat(),
            details={
                "provider": "openai",
                "model": "gpt-4o-mini",
                "decision": "buy",
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "latency_ms": 1_200,
                "failed": None,
            },
        )
        _append_llm_event(
            store,
            timestamp=(now - timedelta(minutes=5)).isoformat(),
            details={
                "provider": "openai",
                "model": "gpt-4o-mini",
                "decision": "hold",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_ms": 400,
                "failed": "safety_rejected",
            },
        )
        _append_llm_event(
            store,
            timestamp=(now - timedelta(minutes=2)).isoformat(),
            details={
                "provider": "deepseek",
                "model": "deepseek-chat",
                "decision": "hold",
                "prompt_tokens": 50,
                "completion_tokens": 20,
                "latency_ms": 700,
                "failed": None,
            },
        )
        _append_llm_event(
            store,
            timestamp=(now - timedelta(minutes=90)).isoformat(),
            details={
                "provider": "openai",
                "model": "stale-model",
                "decision": "sell",
                "prompt_tokens": 999,
                "completion_tokens": 999,
                "latency_ms": 9_999,
                "failed": None,
            },
        )

        response = client.get("/api/v1/ai/insights?minutes=60")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["calls_total"] == 3
    assert body["successful_calls"] == 2
    assert body["failed_calls"] == 1
    assert body["safety_rejections"] == 1
    assert body["success_rate"] == 66.67
    assert body["prompt_tokens"] == 150
    assert body["completion_tokens"] == 60
    assert body["total_tokens"] == 210
    assert body["avg_latency_ms"] == 766.67
    assert body["p95_latency_ms"] == 1_200
    assert body["decisions"] == {"buy": 1, "sell": 0, "hold": 1}
    assert body["failures"] == {"safety_rejected": 1}
    assert body["models"] == [
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "calls": 2,
            "successful_calls": 1,
            "failed_calls": 1,
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "total_tokens": 140,
            "avg_latency_ms": 800.0,
            "p95_latency_ms": 1_200,
        },
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "calls": 1,
            "successful_calls": 1,
            "failed_calls": 0,
            "prompt_tokens": 50,
            "completion_tokens": 20,
            "total_tokens": 70,
            "avg_latency_ms": 700.0,
            "p95_latency_ms": 700,
        },
    ]


def test_llm_insights_requires_bearer_token_when_auth_is_enabled(tmp_path) -> None:
    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "llm_insights_auth.sqlite3"),
            frontend_static_dir=str(tmp_path / "static"),
            auth_api_key="test-secret",
        )
    )
    with TestClient(app) as client:
        denied = client.get("/api/v1/ai/insights")
        allowed = client.get(
            "/api/v1/ai/insights",
            headers={"Authorization": "Bearer test-secret"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_ai_decision_history_replay_and_outcome_are_immutable(tmp_path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.trading.store
        _append_llm_event(
            store,
            timestamp=datetime.utcnow().isoformat(),
            details={
                "provider": "openai",
                "model": "gpt-4o-mini",
                "model_version": "gpt-4o-mini-2026-07",
                "decision": "buy",
                "confidence": 0.82,
                "input_summary": {"symbol": "BTCUSDT"},
                "output_summary": {"decision": "buy"},
                "failed": None,
            },
            symbol="BTCUSDT",
        )

        history = client.get("/api/v1/ai/decisions?symbol=BTCUSDT")
        assert history.status_code == 200, history.text
        event = history.json()["items"][0]
        event_id = event["id"]

        outcome = client.post(
            f"/api/v1/ai/decisions/{event_id}/outcome",
            json={
                "outcome_return_pct": 1.25,
                "mfe_pct": 2.1,
                "mae_pct": -0.4,
                "estimated_cost_usd": 0.02,
                "observation_window": "4h",
            },
        )
        assert outcome.status_code == 200, outcome.text
        assert outcome.json() == {"decision_event_id": event_id, "recorded": True}

        replay = client.get(f"/api/v1/ai/decisions/{event_id}/replay")
        assert replay.status_code == 200, replay.text
        assert replay.json()["decision"]["details"] == event["details"]
        assert replay.json()["outcome"]["details"]["decision_event_id"] == event_id

        insights = client.get("/api/v1/ai/insights?minutes=60")

    assert insights.status_code == 200, insights.text
    assert insights.json()["effectiveness"]["evaluated_signals"] == 1
    assert insights.json()["effectiveness"]["signal_hit_rate"] == 100.0
