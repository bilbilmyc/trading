"""Fail-closed safety checks for LLM-generated trading recommendations.

Provider adapters are intentionally permissive about parsing so that a model
response can still be shown to an operator.  Before that response is allowed
to influence an automated strategy, this module verifies that its protective
levels are usable at the current market price.
"""

from __future__ import annotations

import math
from typing import Any

from app.engine.llm_types import LLMError, LLMErrorKind, LLMResponse


def validate_trade_decision(
    response: LLMResponse,
    *,
    current_price: Any,
) -> LLMResponse:
    """Return a fail-closed response when an actionable decision is unsafe.

    ``hold`` and ``observe`` decisions cannot create an order and are left unchanged.  For
    ``buy`` and ``sell`` decisions, both stop-loss and take-profit are
    required and must be positioned on the protective/profitable side of the
    latest price.  The original token and latency telemetry is retained for
    auditability.
    """
    if response.is_failed or response.decided is None:
        return response

    decision = response.decided
    if decision.decision in {"hold", "observe"}:
        return response

    price = _positive_finite(current_price)
    confidence = _finite_float(decision.confidence)
    stop_loss = _positive_finite(decision.stop_loss)
    take_profit = _positive_finite(decision.take_profit)

    if decision.decision not in {"buy", "sell"}:
        return _reject(response, "模型返回了不支持的交易方向，已拒绝执行。")
    if price is None:
        return _reject(response, "当前市场价格无效，无法校验模型建议，已拒绝执行。")
    if confidence is None or not 0.0 <= confidence <= 1.0:
        return _reject(response, "模型置信度不在 0 到 1 的有效范围内，已拒绝执行。")
    if stop_loss is None or take_profit is None:
        return _reject(response, "可执行建议必须同时提供有效的止损和止盈价格，已拒绝执行。")

    if decision.decision == "buy" and not stop_loss < price < take_profit:
        return _reject(
            response,
            "做多建议的止损、现价、止盈必须满足 止损 < 现价 < 止盈，已拒绝执行。",
        )
    if decision.decision == "sell" and not take_profit < price < stop_loss:
        return _reject(
            response,
            "做空建议的止盈、现价、止损必须满足 止盈 < 现价 < 止损，已拒绝执行。",
        )
    return response


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _positive_finite(value: Any) -> float | None:
    result = _finite_float(value)
    return result if result is not None and result > 0 else None


def _reject(response: LLMResponse, message: str) -> LLMResponse:
    return LLMResponse(
        failed=LLMError(
            kind=LLMErrorKind.SAFETY_REJECTED,
            message=message,
            retryable=False,
        ),
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        latency_ms=response.latency_ms,
    )


__all__ = ["validate_trade_decision"]
