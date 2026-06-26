"""Tests for AI strategy suggester."""

from __future__ import annotations

from dataclasses import asdict

from app.engine.strategy_suggester import StrategySuggestion, suggest_strategy


def test_default_when_too_few_candles() -> None:
    candles = [{"close": 100 + i} for i in range(10)]
    s = suggest_strategy(candles)
    assert s.kind == "sma_crossover"
    assert s.params["short_window"] == 5
    assert s.params["long_window"] == 20


def test_prefer_rsi_when_explicit() -> None:
    candles = [{"close": 100 + i} for i in range(50)]
    s = suggest_strategy(candles, prefer="rsi")
    assert s.kind == "rsi_mean_reversion"


def test_strong_trend_suggests_wider_sma() -> None:
    candles = [{"close": 100 + i} for i in range(50)]
    s = suggest_strategy(candles)
    assert s.kind == "sma_crossover"
    assert s.params["short_window"] >= 10
    assert s.params["long_window"] >= 40


def test_mean_reverting_market_suggests_rsi() -> None:
    candles = [{"close": 100 + (i % 10 - 5) * 0.5} for i in range(60)]
    s = suggest_strategy(candles)
    assert s.kind == "rsi_mean_reversion"


def test_rationale_mentions_trend() -> None:
    candles = [{"close": 100 + (i % 5) * 0.2} for i in range(40)]
    s = suggest_strategy(candles)
    assert "趋势" in s.rationale


def test_to_dict_round_trip() -> None:
    candles = [{"close": 100 + i} for i in range(30)]
    s = suggest_strategy(candles)
    d = asdict(s)
    assert d["kind"] == s.kind
    assert d["params"] == s.params