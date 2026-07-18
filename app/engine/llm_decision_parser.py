"""Defensive parser for structured LLM trading analysis responses."""

from __future__ import annotations

import json
import math
from typing import Any

from app.engine.llm_types import LLMDecided


def _optional_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(minimum, min(maximum, parsed))


def _enum_value(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def _text(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _text_list(value: Any, *, limit: int = 6) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    cleaned = []
    for item in value:
        text = str(item or "").strip()
        if text:
            cleaned.append(text[:240])
        if len(cleaned) >= limit:
            break
    return tuple(cleaned)


def _strip_markdown_fence(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned.startswith("```"):
        return cleaned
    first_newline = cleaned.find("\n")
    if first_newline < 0:
        return cleaned.strip("`").strip()
    cleaned = cleaned[first_newline + 1 :]
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip()


def parse_llm_decision(raw: str, model: str) -> LLMDecided:
    """Parse one model response while preserving a safe, displayable fallback."""
    cleaned = _strip_markdown_fence(raw)
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("top-level JSON must be an object")
    except (json.JSONDecodeError, ValueError):
        return LLMDecided(
            decision="hold",
            confidence=0.0,
            reason=f"LLM 返回格式异常: {raw[:200]}",
            risk_level="high",
            risk_note="解析失败",
            model=model,
            raw_response=raw,
        )

    decision = _enum_value(data.get("decision"), {"buy", "sell", "hold"}, "hold")
    return LLMDecided(
        decision=decision,
        confidence=_bounded_float(
            data.get("confidence"), default=0.5, minimum=0.0, maximum=1.0
        ),
        reason=_text(data.get("reason"), limit=2000),
        stop_loss=_optional_positive_float(data.get("stop_loss")),
        take_profit=_optional_positive_float(data.get("take_profit")),
        risk_level=_enum_value(data.get("risk_level"), {"low", "medium", "high"}, "medium"),
        risk_note=_text(data.get("risk_note"), limit=1000),
        trend=_enum_value(data.get("trend"), {"bullish", "bearish", "neutral"}, "neutral"),
        volatility=_enum_value(data.get("volatility"), {"low", "medium", "high"}, "medium"),
        summary=_text(data.get("summary"), limit=500),
        key_support=_optional_positive_float(data.get("key_support")),
        key_resistance=_optional_positive_float(data.get("key_resistance")),
        entry_zone=_text(data.get("entry_zone"), limit=240),
        position_pct=_bounded_float(
            data.get("position_pct"), default=0.0, minimum=0.0, maximum=1.0
        ),
        bullish_factors=_text_list(data.get("bullish_factors")),
        bearish_factors=_text_list(data.get("bearish_factors")),
        invalidation_condition=_text(data.get("invalidation_condition"), limit=500),
        model=model,
        raw_response=raw,
    )


__all__ = ["parse_llm_decision"]
