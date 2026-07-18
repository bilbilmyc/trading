from __future__ import annotations

from datetime import UTC, datetime

from app.engine.llm_decision_metrics import effectiveness_summary
from app.engine.llm_decision_protocol import validate_decision_protocol
from app.engine.llm_types import LLMDecided, LLMResponse


def _v4_payload(**overrides: object) -> str:
    payload: dict[str, object] = {
        "decision": "buy",
        "confidence": 0.8,
        "regime": "trending",
        "reasons": ["趋势向上", "成交量确认"],
        "risk_factors": ["临近阻力"],
        "stop_loss": 95,
        "take_profit": 110,
        "position_size": 0.2,
        "invalidation_conditions": ["跌破 95"],
        "data_timestamp": "2026-07-17T12:00:00+00:00",
        "model_version": "unit-model",
        "prompt_version": "v4",
    }
    payload.update(overrides)
    import json

    return json.dumps(payload, ensure_ascii=False)


def _response(raw: str, **overrides: object) -> LLMResponse:
    values: dict[str, object] = {
        "decision": "buy",
        "confidence": 0.8,
        "reason": "趋势确认",
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "position_size": 0.2,
        "raw_response": raw,
    }
    values.update(overrides)
    return LLMResponse(decided=LLMDecided(**values))


def test_versioned_protocol_rejects_future_data_and_oversized_position() -> None:
    future = validate_decision_protocol(
        _response(_v4_payload(data_timestamp="2026-07-19T00:00:00+00:00")),
        min_confidence=0.55,
        max_position_pct=0.5,
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert future.is_failed
    assert "未来数据" in future.failed.message

    oversized = validate_decision_protocol(
        _response(_v4_payload(position_size=0.8), position_size=0.8),
        min_confidence=0.55,
        max_position_pct=0.5,
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert oversized.is_failed
    assert "position_size" in oversized.failed.message


def test_low_confidence_action_becomes_observe_with_audit_reason() -> None:
    response = validate_decision_protocol(
        _response(_v4_payload(confidence=0.4), confidence=0.4),
        min_confidence=0.55,
        max_position_pct=0.5,
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert response.is_ok
    assert response.decided.decision == "observe"
    assert response.decided.interception_reasons == ("low_confidence",)


def test_effectiveness_summary_joins_immutable_outcomes_by_decision_event_id() -> None:
    decisions = [
        {
            "id": 11,
            "details": {
                "decision": "buy",
                "confidence": 0.8,
                "model_version": "model-a",
                "failed": None,
            },
        },
        {
            "id": 12,
            "details": {
                "decision": "sell",
                "confidence": 0.6,
                "model_version": "model-b",
                "failed": None,
            },
        },
    ]
    outcomes = [
        {
            "details": {
                "decision_event_id": 11,
                "outcome_return_pct": 2.5,
                "mfe_pct": 4.0,
                "mae_pct": -0.8,
                "estimated_cost_usd": 0.03,
                "strategy_type": "ai",
            }
        },
        {
            "details": {
                "decision_event_id": 12,
                "outcome_return_pct": -1.0,
                "strategy_type": "rule",
            }
        },
    ]

    summary = effectiveness_summary(decisions, outcomes)

    assert summary["evaluated_signals"] == 2
    assert summary["signal_hit_rate"] == 50.0
    assert summary["average_mfe_pct"] == 4.0
    assert summary["average_mae_pct"] == -0.8
    assert summary["cost"] == {"known_cost_usd": 0.03, "events_with_cost": 1, "coverage": 50.0}
    assert summary["ai_vs_rule"]["ai"]["average_return_pct"] == 2.5
    assert summary["ai_vs_rule"]["rule"]["average_return_pct"] == -1.0
