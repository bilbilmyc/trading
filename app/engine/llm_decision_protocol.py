"""Structured protocol and fail-closed policy for AI trading decisions.

This module owns the versioned contract between an LLM provider and the
execution-facing analyzer.  Providers may still parse leniently for operator
visibility, but automated decision paths validate the original JSON against
this contract before a recommendation is allowed to proceed.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.engine.llm_types import LLMError, LLMErrorKind, LLMResponse

DECISIONS = frozenset({"buy", "sell", "hold", "observe"})
ACTIONABLE_DECISIONS = frozenset({"buy", "sell"})
REGIMES = frozenset({"trending", "ranging", "volatile", "breakout", "unknown"})

# Kept as data rather than a Pydantic model so the same contract can be shipped
# in prompts, persisted in audits and checked without adding a runtime dependency.
AI_DECISION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "decision",
        "confidence",
        "regime",
        "reasons",
        "risk_factors",
        "stop_loss",
        "take_profit",
        "position_size",
        "invalidation_conditions",
        "data_timestamp",
        "model_version",
        "prompt_version",
    ],
    "properties": {
        "decision": {"type": "string", "enum": sorted(DECISIONS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "regime": {"type": "string", "enum": sorted(REGIMES)},
        "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "risk_factors": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "stop_loss": {"type": ["number", "null"]},
        "take_profit": {"type": ["number", "null"]},
        "position_size": {"type": "number", "minimum": 0, "maximum": 1},
        "invalidation_conditions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
        "data_timestamp": {"type": "string", "format": "date-time"},
        "model_version": {"type": "string", "minLength": 1},
        "prompt_version": {"type": "string", "minLength": 1},
    },
}


def validate_decision_protocol(
    response: LLMResponse,
    *,
    min_confidence: float,
    max_position_pct: float,
    now: datetime | None = None,
) -> LLMResponse:
    """Validate an LLM response against the structured decision contract.

    A response built directly in Python (``raw_response is None``) is treated
    as a trusted test/internal adapter boundary. Provider-originated output
    must carry the complete JSON protocol. Low-confidence recommendations are
    explicitly downgraded to ``observe`` so their interception is auditable
    without looking like a provider failure.
    """
    if response.is_failed or response.decided is None:
        return response

    decision = response.decided
    raw = decision.raw_response
    if raw is not None:
        payload, error = _load_payload(raw)
        if error is not None:
            return _reject(response, error)
        # Older provider adapters may still return the pre-v4 JSON shape.
        # Validate the full schema once a response declares the versioned
        # contract; legacy output remains subject to the execution guardrails.
        if any(key in payload for key in ("prompt_version", "model_version", "data_timestamp")):
            violations = _schema_violations(payload, max_position_pct=max_position_pct)
            if violations:
                return _reject(response, "AI 决策协议校验失败：" + "；".join(violations))
            timestamp_error = _future_timestamp_error(payload["data_timestamp"], now=now)
            if timestamp_error:
                return _reject(response, timestamp_error)

    if decision.decision not in DECISIONS:
        return _reject(response, "AI 决策包含未支持的 decision 枚举值。")
    if not _in_range(decision.confidence, 0.0, 1.0):
        return _reject(response, "AI 决策 confidence 必须是 0 到 1 的有限数字。")
    if not _in_range(decision.position_size or decision.position_pct, 0.0, max_position_pct):
        return _reject(response, f"AI 建议仓位超过最大允许比例 {max_position_pct:.2f}。")

    if decision.decision in ACTIONABLE_DECISIONS and decision.confidence < min_confidence:
        return LLMResponse(
            decided=replace(
                decision,
                decision="observe",
                reason=(
                    f"低置信度建议已降级为观察：{decision.reason}".strip(": ")
                ),
                interception_reasons=(*decision.interception_reasons, "low_confidence"),
            ),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=response.latency_ms,
        )
    return response


def downgrade_duplicate_decision(response: LLMResponse) -> LLMResponse:
    """Turn a duplicate actionable decision into a non-trading observation."""
    if response.is_failed or response.decided is None:
        return response
    decision = response.decided
    if decision.decision not in ACTIONABLE_DECISIONS:
        return response
    return LLMResponse(
        decided=replace(
            decision,
            decision="observe",
            reason=f"重复的 AI 开仓建议已拦截：{decision.reason}".strip(": "),
            interception_reasons=(*decision.interception_reasons, "duplicate_decision"),
        ),
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        latency_ms=response.latency_ms,
    )


def _load_payload(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        cleaned = cleaned[first_newline + 1 :] if first_newline >= 0 else cleaned.strip("`")
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    try:
        payload = json.loads(cleaned)
    except (TypeError, json.JSONDecodeError):
        return None, "AI 返回内容不是有效 JSON。"
    if not isinstance(payload, dict):
        return None, "AI 返回 JSON 顶层必须是对象。"
    return payload, None


def _schema_violations(payload: dict[str, Any], *, max_position_pct: float) -> list[str]:
    missing = [key for key in AI_DECISION_JSON_SCHEMA["required"] if key not in payload]
    if missing:
        return ["缺少字段 " + ", ".join(missing)]

    errors: list[str] = []
    if str(payload["decision"]).lower() not in DECISIONS:
        errors.append("decision 枚举无效")
    if not _in_range(payload["confidence"], 0.0, 1.0):
        errors.append("confidence 必须在 0 到 1")
    if str(payload["regime"]).lower() not in REGIMES:
        errors.append("regime 枚举无效")
    for name in ("reasons", "risk_factors", "invalidation_conditions"):
        value = payload[name]
        if not isinstance(value, list) or len(value) > 6 or any(not str(item).strip() for item in value):
            errors.append(f"{name} 必须是最多 6 项的非空字符串数组")
    for name in ("stop_loss", "take_profit"):
        value = payload[name]
        if value is not None and not _positive_finite(value):
            errors.append(f"{name} 必须是正数或 null")
    if not _in_range(payload["position_size"], 0.0, max_position_pct):
        errors.append(f"position_size 必须在 0 到 {max_position_pct:.2f}")
    for name in ("model_version", "prompt_version"):
        if not isinstance(payload[name], str) or not payload[name].strip():
            errors.append(f"{name} 不能为空")
    return errors


def _future_timestamp_error(value: Any, *, now: datetime | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "data_timestamp 必须是 ISO-8601 时间。"
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "data_timestamp 不是有效 ISO-8601 时间。"
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    if timestamp > reference.astimezone(UTC):
        return "data_timestamp 晚于当前时间，已拒绝未来数据决策。"
    return None


def _in_range(value: Any, minimum: float, maximum: float) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric) and minimum <= numeric <= maximum


def _positive_finite(value: Any) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric) and numeric > 0


def _reject(response: LLMResponse, message: str) -> LLMResponse:
    return LLMResponse(
        failed=LLMError(kind=LLMErrorKind.SAFETY_REJECTED, message=message, retryable=False),
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        latency_ms=response.latency_ms,
    )


__all__ = [
    "ACTIONABLE_DECISIONS",
    "AI_DECISION_JSON_SCHEMA",
    "DECISIONS",
    "REGIMES",
    "downgrade_duplicate_decision",
    "validate_decision_protocol",
]
