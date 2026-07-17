"""Local availability controls for strategy-scoped LLM calls.

The governor is deliberately owned by an ``LLMAnalyzer`` instance.  That gives
long-running LLM strategies a cheap protection against request bursts and
repeated upstream failures without turning cached results into failed calls.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from app.engine.llm_types import LLMError, LLMErrorKind, LLMResponse


class LLMCallGovernor:
    """Apply a minimum request interval and a consecutive-failure circuit breaker."""

    def __init__(
        self,
        *,
        min_request_interval_seconds: float = 0.0,
        circuit_failure_threshold: int = 3,
        circuit_cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval_seconds = max(0.0, float(min_request_interval_seconds))
        self._failure_threshold = max(1, int(circuit_failure_threshold))
        self._cooldown_seconds = max(0.0, float(circuit_cooldown_seconds))
        self._clock = clock
        self._last_request_at: float | None = None
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def before_provider_call(self) -> LLMError | None:
        """Reserve a real provider call, or return a structured local rejection."""
        now = self._clock()
        if self._circuit_open_until:
            if now < self._circuit_open_until:
                remaining = max(1, math.ceil(self._circuit_open_until - now))
                return LLMError(
                    kind=LLMErrorKind.CIRCUIT_OPEN,
                    message=f"LLM 连续调用失败，熔断中，请在约 {remaining} 秒后重试。",
                    retryable=True,
                )
            self._circuit_open_until = 0.0
            self._consecutive_failures = 0

        if self._last_request_at is not None and self._min_interval_seconds > 0:
            remaining = self._min_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                return LLMError(
                    kind=LLMErrorKind.RATE_LIMITED,
                    message=f"LLM 策略调用过于频繁，请在约 {math.ceil(remaining)} 秒后重试。",
                    retryable=True,
                )

        self._last_request_at = now
        return None

    def record_provider_response(self, response: LLMResponse) -> None:
        """Update failure state after one real provider call has completed."""
        # A guardrail rejection means the provider was available and returned a
        # model response; it must not make an upstream availability incident
        # worse. Successful decisions likewise clear the failure streak.
        if response.failed is None or response.failed.kind is LLMErrorKind.SAFETY_REJECTED:
            self._consecutive_failures = 0
            return

        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._circuit_open_until = self._clock() + self._cooldown_seconds


__all__ = ["LLMCallGovernor"]
