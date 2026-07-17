"""Tests for local LLM availability controls."""

from __future__ import annotations

from app.engine.llm_governor import LLMCallGovernor
from app.engine.llm_types import LLMDecided, LLMError, LLMErrorKind, LLMResponse


class ManualClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _ok() -> LLMResponse:
    return LLMResponse(decided=LLMDecided(decision="hold", confidence=0.0, reason="ok"))


def _failed(kind: LLMErrorKind = LLMErrorKind.NETWORK) -> LLMResponse:
    return LLMResponse(failed=LLMError(kind=kind, message="upstream failed", retryable=True))


def test_min_interval_rejects_without_reserving_second_provider_call() -> None:
    clock = ManualClock()
    governor = LLMCallGovernor(min_request_interval_seconds=10, clock=clock)

    assert governor.before_provider_call() is None
    clock.advance(4)
    rejected = governor.before_provider_call()

    assert rejected is not None
    assert rejected.kind is LLMErrorKind.RATE_LIMITED
    assert rejected.retryable is True

    clock.advance(6)
    assert governor.before_provider_call() is None


def test_consecutive_failures_open_circuit_then_cooldown_recovers() -> None:
    clock = ManualClock()
    governor = LLMCallGovernor(
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=30,
        clock=clock,
    )

    assert governor.before_provider_call() is None
    governor.record_provider_response(_failed())
    assert governor.before_provider_call() is None
    governor.record_provider_response(_failed(LLMErrorKind.TIMEOUT))

    rejected = governor.before_provider_call()
    assert rejected is not None
    assert rejected.kind is LLMErrorKind.CIRCUIT_OPEN
    assert rejected.retryable is True

    clock.advance(30)
    assert governor.before_provider_call() is None


def test_success_and_safety_rejection_clear_availability_failure_streak() -> None:
    governor = LLMCallGovernor(circuit_failure_threshold=2, circuit_cooldown_seconds=30)

    assert governor.before_provider_call() is None
    governor.record_provider_response(_failed())
    governor.record_provider_response(_ok())
    assert governor.before_provider_call() is None
    governor.record_provider_response(_failed())
    assert governor.before_provider_call() is None

    governor.record_provider_response(
        _failed(LLMErrorKind.SAFETY_REJECTED)
    )
    assert governor.before_provider_call() is None
