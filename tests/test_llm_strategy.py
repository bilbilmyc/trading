"""Tests for LLMStrategy — signal generation from LLM decisions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from app.strategies.base import Signal, SignalAction
from app.strategies.llm_analyzer import LLMAnalysisResult
from app.strategies.llm_strategy import LLMStrategy


def _candles(prices: List[float]) -> List[Dict[str, Any]]:
    return [
        {
            "open_time": datetime(2026, 1, 1) + timedelta(hours=i),
            "open": p,
            "high": p,
            "low": p,
            "close": p,
            "volume": 1.0,
        }
        for i, p in enumerate(prices)
    ]


def _result(decision: str, confidence: float = 0.8, stop_loss: float = None, take_profit: float = None) -> LLMAnalysisResult:
    return LLMAnalysisResult(
        decision=decision,
        confidence=confidence,
        reason="test reason",
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_level="medium",
        risk_note="",
        model="gpt-4o-mini",
        analysis_time=datetime.utcnow().isoformat(),
        analyzed_symbol="BTCUSDT",
        analyzed_interval="1h",
        candle_count=30,
        cache_hit=False,
    )


def _strategy(analyzer) -> LLMStrategy:
    return LLMStrategy(
        analyzer=analyzer,
        default_order_amount_usdt=100.0,
        min_confidence=0.5,
        min_candles=10,
        max_candles=80,
    )


@pytest.mark.asyncio
async def test_no_signal_without_cached_candles() -> None:
    s = _strategy(analyzer=AsyncMock())
    assert await s.generate_signals("BTCUSDT") is None


@pytest.mark.asyncio
async def test_no_signal_below_min_candles() -> None:
    analyzer = AsyncMock()
    s = _strategy(analyzer=analyzer)
    for c in _candles([100] * 5):
        await s.on_market_data("BTCUSDT", c)
    assert await s.generate_signals("BTCUSDT") is None


@pytest.mark.asyncio
async def test_hold_decision_emits_no_signal() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw = AsyncMock(return_value=_result("hold"))
    s = _strategy(analyzer=analyzer)
    for c in _candles([100] * 30):
        await s.on_market_data("BTCUSDT", c)
    assert await s.generate_signals("BTCUSDT") is None


@pytest.mark.asyncio
async def test_observe_decision_emits_no_signal_even_when_confident() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw = AsyncMock(return_value=_result("observe", confidence=0.9))
    s = _strategy(analyzer=analyzer)
    for candle in _candles([100] * 30):
        await s.on_market_data("BTCUSDT", candle)

    assert await s.generate_signals("BTCUSDT") is None


@pytest.mark.asyncio
async def test_low_confidence_emits_no_signal() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw = AsyncMock(return_value=_result("buy", confidence=0.3))
    s = _strategy(analyzer=analyzer)
    for c in _candles([100] * 30):
        await s.on_market_data("BTCUSDT", c)
    assert await s.generate_signals("BTCUSDT") is None


@pytest.mark.asyncio
async def test_buy_signal_when_llm_says_buy() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw = AsyncMock(return_value=_result("buy", confidence=0.7, stop_loss=95.0, take_profit=110.0))
    s = _strategy(analyzer=analyzer)
    for c in _candles([100] * 30):
        await s.on_market_data("BTCUSDT", c)
    sig = await s.generate_signals("BTCUSDT")
    assert sig is not None
    assert sig.action == SignalAction.BUY
    assert sig.stop_loss == 95.0
    assert sig.take_profit == 110.0


@pytest.mark.asyncio
async def test_sell_signal_when_llm_says_sell() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw = AsyncMock(return_value=_result("sell", confidence=0.8))
    s = _strategy(analyzer=analyzer)
    for c in _candles([100] * 30):
        await s.on_market_data("BTCUSDT", c)
    sig = await s.generate_signals("BTCUSDT")
    assert sig is not None
    assert sig.action == SignalAction.SELL


@pytest.mark.asyncio
async def test_quantity_calculated_from_order_amount() -> None:
    """Quantity = order_amount_usdt / current_price, rounded."""
    analyzer = AsyncMock()
    analyzer.analyze_raw = AsyncMock(return_value=_result("buy", confidence=0.7))
    s = _strategy(analyzer=analyzer)
    # Last close = 200 → quantity = 100 / 200 = 0.5
    for c in _candles([100] * 29 + [200]):
        await s.on_market_data("BTCUSDT", c)
    sig = await s.generate_signals("BTCUSDT")
    assert sig.quantity == 0.5


@pytest.mark.asyncio
async def test_signal_metadata_carries_reason_and_risk() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw = AsyncMock(return_value=_result("buy", confidence=0.8))
    s = _strategy(analyzer=analyzer)
    for c in _candles([100] * 30):
        await s.on_market_data("BTCUSDT", c)
    sig = await s.generate_signals("BTCUSDT")
    assert sig.metadata["reason"] == "test reason"
    assert sig.metadata["source"] == "llm_strategy"


@pytest.mark.asyncio
async def test_analyzer_exception_returns_none_signal() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw = AsyncMock(side_effect=RuntimeError("API down"))
    s = _strategy(analyzer=analyzer)
    for c in _candles([100] * 30):
        await s.on_market_data("BTCUSDT", c)
    assert await s.generate_signals("BTCUSDT") is None


@pytest.mark.asyncio
async def test_kline_buffer_bounded_at_max_candles() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw = AsyncMock(return_value=_result("hold"))
    s = _strategy(analyzer=analyzer)
    for c in _candles([100] * 200):
        await s.on_market_data("BTCUSDT", c)
    assert len(s._klines["BTCUSDT"]) == 80  # max_candles cap


def test_get_last_result_returns_cached() -> None:
    analyzer = AsyncMock()
    s = _strategy(analyzer=analyzer)
    # No record yet.
    assert s.get_last_result("BTCUSDT") is None
    assert s.get_last_signal("BTCUSDT") is None
    assert s.get_kline_count("BTCUSDT") == 0


@pytest.mark.asyncio
async def test_start_clears_state() -> None:
    s = _strategy(analyzer=AsyncMock())
    for c in _candles([100] * 30):
        await s.on_market_data("BTCUSDT", c)
    assert s.get_kline_count("BTCUSDT") == 30
    await s.start()
    assert s.get_kline_count("BTCUSDT") == 0


@pytest.mark.asyncio
async def test_stop_clears_state() -> None:
    s = _strategy(analyzer=AsyncMock())
    for c in _candles([100] * 30):
        await s.on_market_data("BTCUSDT", c)
    await s.stop()
    assert s.get_kline_count("BTCUSDT") == 0