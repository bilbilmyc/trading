"""Strategy recommender — combines heuristics + (optional) LLM input.

Produces a single StrategySuggestion from a list of klines. Optionally
takes an LLM analysis result to enrich the rationale.
"""

from __future__ import annotations

from typing import Any

from app.engine.strategy_suggester import (
    suggest_strategy as heuristic_suggest,
)


def recommend_strategy(
    candles: list,
    *,
    llm_rationale: str | None = None,
    llm_decision: str | None = None,
    llm_confidence: float | None = None,
    prefer: str | None = None,
) -> dict[str, Any]:
    """Combine heuristic suggestion with optional LLM insights.

    Returns a JSON-serializable dict with `kind`, `params`, and
    `rationale` (LLM rationale preferred when present and confident).
    """
    suggestion = heuristic_suggest(candles, prefer=prefer)

    rationale = suggestion.rationale
    if llm_rationale and llm_confidence is not None and llm_confidence >= 0.5:
        rationale = f"LLM: {llm_rationale}\n\n启发式: {suggestion.rationale}"

    out: dict[str, Any] = {
        "kind": suggestion.kind,
        "params": dict(suggestion.params),
        "rationale": rationale,
        "llm_decision": llm_decision,
        "llm_confidence": llm_confidence,
    }
    return out


__all__ = ["recommend_strategy"]
