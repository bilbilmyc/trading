"""Tests for strategy recommender."""

from __future__ import annotations

from typing import Any, Dict, List

from app.engine.strategy_recommender import recommend_strategy


def _candles(prices: List[float]) -> List[Dict[str, Any]]:
    return [
        {"close": p, "open_time": f"2026-01-01T{i:02d}:00:00"}
        for i, p in enumerate(prices)
    ]


def test_recommend_uses_heuristic_when_no_llm() -> None:
    out = recommend_strategy(_candles([100] * 30))
    assert out["kind"] in ("sma_crossover", "rsi_mean_reversion")
    assert "rationale" in out
    assert "params" in out


def test_recommend_includes_llm_decision_when_present() -> None:
    out = recommend_strategy(
        _candles([100] * 30),
        llm_decision="buy",
        llm_confidence=0.8,
        llm_rationale="Strong uptrend with momentum",
    )
    assert out["llm_decision"] == "buy"
    assert out["llm_confidence"] == 0.8
    assert "Strong uptrend" in out["rationale"]


def test_recommend_skips_llm_when_low_confidence() -> None:
    """Low-confidence LLM input is ignored — heuristic stands alone."""
    out = recommend_strategy(
        _candles([100] * 30),
        llm_decision="buy",
        llm_confidence=0.3,
        llm_rationale="Weak signal",
    )
    assert out["llm_confidence"] == 0.3
    # No "LLM:" prefix in rationale because confidence < 0.5.
    assert "LLM:" not in out["rationale"]


def test_recommend_params_copied_from_heuristic() -> None:
    out = recommend_strategy(_candles([100] * 30))
    assert "short_window" in out["params"] or "period" in out["params"]


def test_recommend_with_empty_candles_uses_default_sma() -> None:
    out = recommend_strategy([])
    assert out["kind"] == "sma_crossover"
    assert out["params"]["short_window"] == 5