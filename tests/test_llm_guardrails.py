"""Tests for fail-closed validation of actionable LLM recommendations."""

from __future__ import annotations

from app.engine.llm_guardrails import validate_trade_decision
from app.engine.llm_types import LLMDecided, LLMErrorKind, LLMResponse


def _response(
    decision: str,
    *,
    confidence: float = 0.8,
    stop_loss: float | None = 95.0,
    take_profit: float | None = 110.0,
) -> LLMResponse:
    return LLMResponse(
        decided=LLMDecided(
            decision=decision,
            confidence=confidence,
            reason="test",
            stop_loss=stop_loss,
            take_profit=take_profit,
            model="test-model",
        ),
        prompt_tokens=12,
        completion_tokens=8,
        latency_ms=34,
    )


def test_valid_long_levels_are_allowed_and_keep_telemetry() -> None:
    result = validate_trade_decision(_response("buy"), current_price=100.0)

    assert result.is_ok
    assert result.decided.decision == "buy"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 8
    assert result.latency_ms == 34


def test_valid_short_levels_are_allowed() -> None:
    result = validate_trade_decision(
        _response("sell", stop_loss=105.0, take_profit=90.0), current_price=100.0
    )

    assert result.is_ok
    assert result.decided.decision == "sell"


def test_actionable_decision_requires_both_protective_levels() -> None:
    result = validate_trade_decision(
        _response("buy", stop_loss=None, take_profit=110.0), current_price=100.0
    )

    assert result.is_failed
    assert result.failed.kind == LLMErrorKind.SAFETY_REJECTED
    assert "止损" in result.failed.message


def test_rejects_long_levels_on_the_wrong_side_of_market() -> None:
    result = validate_trade_decision(
        _response("buy", stop_loss=105.0, take_profit=95.0), current_price=100.0
    )

    assert result.is_failed
    assert result.failed.kind == LLMErrorKind.SAFETY_REJECTED


def test_rejects_short_levels_on_the_wrong_side_of_market() -> None:
    result = validate_trade_decision(
        _response("sell", stop_loss=95.0, take_profit=105.0), current_price=100.0
    )

    assert result.is_failed
    assert result.failed.kind == LLMErrorKind.SAFETY_REJECTED


def test_hold_is_not_rejected_for_missing_exit_levels() -> None:
    result = validate_trade_decision(
        _response("hold", stop_loss=None, take_profit=None), current_price=100.0
    )

    assert result.is_ok
    assert result.decided.decision == "hold"
