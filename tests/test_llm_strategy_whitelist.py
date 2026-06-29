"""Tests for the LLM strategy symbol whitelist.

Defense-in-depth: even if the LLM is asked to analyze a symbol, the
strategy itself must refuse to generate a signal for symbols that are
not on a configured whitelist. This prevents accidental trading on
typos, wrong tickers, or symbols outside the user's intent.

When `allowed_symbols` is empty/None, all symbols pass (backward compat
for personal-localhost setups where the user wants zero friction).

When `allowed_symbols` is set, only those symbols get past the gate.
The LLM is NOT called for blocked symbols — saves tokens + latency.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.strategies.llm_analyzer import LLMAnalysisResult
from app.strategies.llm_strategy import LLMStrategy


class RecordingAnalyzer:
    """Test double for LLMAnalyzer — records every call without doing real work."""

    def __init__(self, result: Optional[LLMAnalysisResult] = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._result = result or LLMAnalysisResult(
            decision="buy",
            confidence=0.9,
            reason="test buy",
            stop_loss=49000.0,
            take_profit=51000.0,
            risk_level="low",
            analyzed_symbol="",
            analyzed_interval="",
            candle_count=0,
            model="test",
            analysis_time="2026-01-01T00:00:00",
        )

    async def analyze_raw(self, **kwargs) -> LLMAnalysisResult:
        self.calls.append(kwargs)
        result = LLMAnalysisResult(**{**self._result.__dict__, "analyzed_symbol": kwargs.get("symbol", "")})
        return result

    async def close(self) -> None:
        pass


def _build_klines(n: int = 30, last_price: float = 50000.0) -> List[Dict[str, Any]]:
    """Build a minimal K-line series large enough to pass min_candles."""
    return [
        {
            "open": last_price,
            "high": last_price + 10,
            "low": last_price - 10,
            "close": last_price,
            "volume": 100.0,
            "open_time": f"2026-01-{(i % 28) + 1:02d} 00:00",
        }
        for i in range(n)
    ]


async def _seed_klines(strategy: LLMStrategy, symbol: str, n: int = 30) -> None:
    for k in _build_klines(n):
        await strategy.on_market_data(symbol, k)


# ── Whitelist disabled (default) ────────────────────────────────────


@pytest.mark.asyncio
async def test_no_whitelist_allows_any_symbol() -> None:
    """When allowed_symbols is None, every symbol passes through."""
    analyzer = RecordingAnalyzer()
    strategy = LLMStrategy(analyzer=analyzer)  # no whitelist

    await _seed_klines(strategy, "BTCUSDT")
    signal = await strategy.generate_signals("BTCUSDT")
    assert signal is not None
    assert signal.symbol == "BTCUSDT"
    assert len(analyzer.calls) == 1


@pytest.mark.asyncio
async def test_empty_whitelist_allows_any_symbol() -> None:
    """Empty list (explicit) behaves the same as None — full access."""
    analyzer = RecordingAnalyzer()
    strategy = LLMStrategy(analyzer=analyzer, allowed_symbols=[])

    await _seed_klines(strategy, "ETHUSDT")
    signal = await strategy.generate_signals("ETHUSDT")
    assert signal is not None
    assert len(analyzer.calls) == 1


# ── Whitelist enabled ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_whitelisted_symbol_proceeds() -> None:
    """A symbol on the whitelist goes through and produces a signal."""
    analyzer = RecordingAnalyzer()
    strategy = LLMStrategy(analyzer=analyzer, allowed_symbols=["BTCUSDT", "ETHUSDT"])

    await _seed_klines(strategy, "BTCUSDT")
    signal = await strategy.generate_signals("BTCUSDT")
    assert signal is not None
    assert signal.symbol == "BTCUSDT"
    assert len(analyzer.calls) == 1


@pytest.mark.asyncio
async def test_non_whitelisted_symbol_blocked_silently() -> None:
    """A symbol NOT on the whitelist returns None and does NOT call the LLM."""
    analyzer = RecordingAnalyzer()
    strategy = LLMStrategy(analyzer=analyzer, allowed_symbols=["BTCUSDT"])

    await _seed_klines(strategy, "DOGEUSDT")
    signal = await strategy.generate_signals("DOGEUSDT")
    assert signal is None
    # Critical: the LLM was never called for the blocked symbol.
    assert len(analyzer.calls) == 0


@pytest.mark.asyncio
async def test_mixed_symbols_filtered_correctly() -> None:
    """Whitelist filters per-symbol even when multiple symbols share the strategy."""
    analyzer = RecordingAnalyzer()
    strategy = LLMStrategy(analyzer=analyzer, allowed_symbols=["BTCUSDT"])

    await _seed_klines(strategy, "BTCUSDT")
    await _seed_klines(strategy, "SOLUSDT")

    s1 = await strategy.generate_signals("BTCUSDT")
    s2 = await strategy.generate_signals("SOLUSDT")

    assert s1 is not None
    assert s2 is None
    # Only the whitelisted symbol triggered an LLM call.
    assert len(analyzer.calls) == 1
    assert analyzer.calls[0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_whitelist_check_is_case_sensitive_uppercase() -> None:
    """Whitelist is exact match (case-sensitive) — typical for symbol codes."""
    analyzer = RecordingAnalyzer()
    strategy = LLMStrategy(analyzer=analyzer, allowed_symbols=["BTCUSDT"])

    await _seed_klines(strategy, "btcusdt")
    signal = await strategy.generate_signals("btcusdt")
    # Wrong case → blocked (crypto symbols are uppercase by convention).
    assert signal is None
    assert len(analyzer.calls) == 0
