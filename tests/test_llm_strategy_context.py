"""Tests for LLM context provider wiring.

Slice 2 of P1-4: the prompt template now expects `risk_context` and
`trade_history` to be passed in, but the strategy wasn't actually
populating them. These tests pin the wiring: when a context provider
is configured, the strategy must pull fresh data per call and pass it
to the analyzer.

Without a provider, the strategy behaves exactly as before (no risk /
trade blocks in the prompt) — backward compatible.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.strategies.llm_analyzer import LLMAnalysisResult
from app.strategies.llm_strategy import LLMStrategy


class RecordingAnalyzer:
    """Test double — records every call so we can assert what was passed in."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def analyze_raw(self, **kwargs) -> LLMAnalysisResult:
        self.calls.append(kwargs)
        return LLMAnalysisResult(
            decision="buy",
            confidence=0.9,
            reason="ok",
            stop_loss=49000.0,
            take_profit=51000.0,
            risk_level="low",
            analyzed_symbol=kwargs.get("symbol", ""),
            analyzed_interval="",
            candle_count=0,
            model="test",
            analysis_time="2026-01-01T00:00:00",
        )

    async def close(self) -> None:
        pass


class FakeContextProvider:
    """Test double — returns canned risk + trade data, records queries."""

    def __init__(
        self,
        risk: Optional[Dict[str, Any]] = None,
        history: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.risk = risk or {
            "daily_pnl": -42.0,
            "current_drawdown_pct": 0.07,
            "kill_switch_enabled": False,
            "orders_last_minute": 1,
            "max_orders_per_minute": 5,
        }
        self.history = history or {
            "total_trades": 20,
            "winning_trades": 12,
            "losing_trades": 8,
            "win_rate": 0.6,
            "avg_win": 10.0,
            "avg_loss": -5.0,
            "max_consecutive_wins": 3,
            "max_consecutive_losses": 2,
        }
        self.risk_calls: List[str] = []
        self.trade_calls: List[str] = []

    async def get_risk_context(self) -> Optional[Dict[str, Any]]:
        self.risk_calls.append("get_risk_context")
        return self.risk

    async def get_trade_history(self, symbol: str) -> Optional[Dict[str, Any]]:
        self.trade_calls.append(symbol)
        return self.history


def _build_klines(n: int = 30, last_price: float = 50000.0) -> List[Dict[str, Any]]:
    return [
        {
            "open": last_price, "high": last_price + 10,
            "low": last_price - 10, "close": last_price,
            "volume": 100.0,
            "open_time": f"2026-01-{(i % 28) + 1:02d} 00:00",
        }
        for i in range(n)
    ]


async def _seed(strategy: LLMStrategy, symbol: str) -> None:
    for k in _build_klines():
        await strategy.on_market_data(symbol, k)


# ── No provider (backward compat) ─────────────────────────────────


@pytest.mark.asyncio
async def test_no_provider_passes_no_risk_or_history() -> None:
    """Without a provider, risk_context / trade_history are None."""
    analyzer = RecordingAnalyzer()
    strategy = LLMStrategy(analyzer=analyzer)

    await _seed(strategy, "BTCUSDT")
    await strategy.generate_signals("BTCUSDT")

    assert len(analyzer.calls) == 1
    call = analyzer.calls[0]
    assert call.get("risk_context") is None
    assert call.get("trade_history") is None


# ── Provider attached ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_passes_risk_and_history_to_analyzer() -> None:
    """With a provider, the analyzer receives both blocks on every call."""
    analyzer = RecordingAnalyzer()
    provider = FakeContextProvider()
    strategy = LLMStrategy(analyzer=analyzer, context_provider=provider)

    await _seed(strategy, "BTCUSDT")
    await strategy.generate_signals("BTCUSDT")

    assert len(analyzer.calls) == 1
    call = analyzer.calls[0]
    # Risk block reaches the analyzer
    assert call["risk_context"]["daily_pnl"] == -42.0
    assert call["risk_context"]["current_drawdown_pct"] == 0.07
    assert call["risk_context"]["kill_switch_enabled"] is False
    # Trade history block reaches the analyzer, scoped to the requested symbol
    assert call["trade_history"]["total_trades"] == 20
    assert call["trade_history"]["win_rate"] == 0.6
    # Provider was called once for each block
    assert len(provider.risk_calls) == 1
    assert provider.trade_calls == ["BTCUSDT"]


@pytest.mark.asyncio
async def test_provider_called_with_correct_symbol() -> None:
    """get_trade_history must be called with the signal's symbol, not any other."""
    analyzer = RecordingAnalyzer()
    provider = FakeContextProvider()
    strategy = LLMStrategy(analyzer=analyzer, context_provider=provider)

    await _seed(strategy, "ETHUSDT")
    await strategy.generate_signals("ETHUSDT")

    assert provider.trade_calls == ["ETHUSDT"]


@pytest.mark.asyncio
async def test_risk_block_reraised_per_signal_call() -> None:
    """Risk context is fetched fresh on every generate_signals call (not cached)."""
    analyzer = RecordingAnalyzer()
    provider = FakeContextProvider()
    strategy = LLMStrategy(analyzer=analyzer, context_provider=provider)

    await _seed(strategy, "BTCUSDT")
    await strategy.generate_signals("BTCUSDT")
    await strategy.generate_signals("BTCUSDT")

    # Two signal calls → two risk fetches (so kill switch / drawdown are live)
    assert len(provider.risk_calls) == 2
    assert len(analyzer.calls) == 2


@pytest.mark.asyncio
async def test_provider_returning_none_passes_through() -> None:
    """If the provider returns None, the analyzer sees None (graceful degrade)."""

    class NoneProvider:
        async def get_risk_context(self):
            return None

        async def get_trade_history(self, symbol):
            return None

    analyzer = RecordingAnalyzer()
    strategy = LLMStrategy(analyzer=analyzer, context_provider=NoneProvider())

    await _seed(strategy, "BTCUSDT")
    await strategy.generate_signals("BTCUSDT")

    call = analyzer.calls[0]
    assert call["risk_context"] is None
    assert call["trade_history"] is None
