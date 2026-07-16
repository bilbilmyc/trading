"""P0 safety tests for the LLM signal filter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.engine.llm_filter import LLMSignalFilter
from app.strategies.base import Signal, SignalAction
from app.strategies.llm_analyzer import LLMAnalysisResult


def _signal() -> Signal:
    return Signal(
        symbol="BTCUSDT",
        action=SignalAction.BUY,
        strength=0.9,
        quantity=0.001,
        price=100.0,
    )


def _result(**overrides) -> LLMAnalysisResult:
    values = {
        "decision": "buy",
        "confidence": 0.8,
        "reason": "trend confirms",
        "analyzed_symbol": "BTCUSDT",
    }
    values.update(overrides)
    return LLMAnalysisResult(**values)


@pytest.mark.asyncio
async def test_missing_price_fails_closed_without_calling_analyzer() -> None:
    analyzer = AsyncMock()
    filter_ = LLMSignalFilter(analyzer=analyzer)
    signal = _signal().model_copy(update={"price": None})

    allowed = await filter_.check("binance_usdm", "sma", signal)

    assert allowed is False
    analyzer.analyze_raw.assert_not_awaited()


@pytest.mark.asyncio
async def test_analyzer_exception_fails_closed() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw.side_effect = RuntimeError("provider unavailable")
    filter_ = LLMSignalFilter(analyzer=analyzer)

    allowed = await filter_.check("binance_usdm", "sma", _signal())

    assert allowed is False


@pytest.mark.asyncio
async def test_failed_analysis_result_fails_closed() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw.return_value = _result(
        decision="hold",
        confidence=0.0,
        error_kind="timeout",
    )
    filter_ = LLMSignalFilter(analyzer=analyzer)

    allowed = await filter_.check("binance_usdm", "sma", _signal())

    assert allowed is False


@pytest.mark.asyncio
async def test_matching_high_confidence_analysis_is_allowed() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw.return_value = _result()
    filter_ = LLMSignalFilter(analyzer=analyzer, min_confidence=0.5)

    allowed = await filter_.check("binance_usdm", "sma", _signal())

    assert allowed is True


@pytest.mark.asyncio
async def test_context_market_data_is_forwarded_to_analyzer() -> None:
    analyzer = AsyncMock()
    analyzer.analyze_raw.return_value = _result()
    filter_ = LLMSignalFilter(analyzer=analyzer)
    signal = _signal().model_copy(update={"price": None})
    ticker = {"symbol": "BTCUSDT", "last_price": 101.0}
    klines = [{"open_time": 1, "close": 101.0}]

    allowed = await filter_.check(
        signal,
        {"ticker": ticker, "klines": klines, "interval": "5m"},
    )

    assert allowed is True
    analyzer.analyze_raw.assert_awaited_once_with(
        ticker=ticker,
        klines=klines,
        symbol="BTCUSDT",
        interval="5m",
        position_context=None,
    )
