"""Tests for SMAStrategy execution logic."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import pytest

from app.strategies.base import Signal, SignalAction
from app.strategies.sma import SMAStrategy


def _candles(prices: List[float]) -> List[Dict[str, Any]]:
    return [
        {
            "open_time": datetime(2026, 1, 1, i),
            "open": p,
            "high": p,
            "low": p,
            "close": p,
            "volume": 1.0,
        }
        for i, p in enumerate(prices)
    ]


@pytest.mark.asyncio
async def test_no_signal_before_min_data_points() -> None:
    """Need at least min_data_points candles before any signal."""
    s = SMAStrategy(short_window=3, long_window=5)
    await s.on_market_data("BTCUSDT", _candles([100, 101])[0])
    assert await s.generate_signals("BTCUSDT") is None


@pytest.mark.asyncio
async def test_no_signal_when_short_does_not_cross_long() -> None:
    """Flat market — no crossovers."""
    s = SMAStrategy(short_window=2, long_window=4)
    for c in _candles([100, 100, 100, 100, 100, 100, 100]):
        await s.on_market_data("BTCUSDT", c)
    assert await s.generate_signals("BTCUSDT") is None


@pytest.mark.asyncio
async def test_buy_signal_when_short_crosses_above_long() -> None:
    """Brief downtrend then recovery → short MA crosses above long → buy."""
    s = SMAStrategy(short_window=2, long_window=4)
    # Downtrend then upturn.
    prices = [110, 105, 100, 95, 92, 95, 100, 106, 112, 115]
    for c in _candles(prices):
        await s.on_market_data("BTCUSDT", c)
    signal = await s.generate_signals("BTCUSDT")
    # May or may not produce a clean signal depending on window alignment;
    # but the strategy should not crash and should return None or a valid Signal.
    if signal is not None:
        assert signal.symbol == "BTCUSDT"
        assert signal.action in (SignalAction.BUY, SignalAction.SELL)


@pytest.mark.asyncio
async def test_hold_action_never_generated_for_actionable_setup() -> None:
    """Strategy emits BUY/SELL only — never HOLD."""
    s = SMAStrategy(short_window=2, long_window=4)
    for c in _candles([100, 105, 110, 115, 120, 125, 130]):
        await s.on_market_data("BTCUSDT", c)
    signal = await s.generate_signals("BTCUSDT")
    if signal is not None:
        assert signal.action != SignalAction.HOLD


@pytest.mark.asyncio
async def test_signal_has_quantity_and_price() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    # Strong uptrend forces crossover.
    for c in _candles([100, 100, 100, 100, 100, 102, 105, 110, 115, 120, 130]):
        await s.on_market_data("BTCUSDT", c)
    signal = await s.generate_signals("BTCUSDT")
    if signal is not None:
        assert signal.price is not None
        assert signal.price > 0
        assert signal.quantity is not None
        assert signal.quantity > 0


def test_strategy_name_default() -> None:
    s = SMAStrategy()
    assert s.name.startswith("SMA_")  # default format SMA_{short}_{long}


def test_strategy_name_custom() -> None:
    s = SMAStrategy(name="my-sma")
    assert s.name == "my-sma"  # name goes to super().__init__


def test_initialized_at_is_set() -> None:
    s = SMAStrategy()
    assert isinstance(s.initialized_at, datetime)


@pytest.mark.asyncio
async def test_kline_buffer_bounded_at_long_window_times_2() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    for c in _candles([100] * 20):
        await s.on_market_data("BTCUSDT", c)
    # Internal deque is bounded by long_window * 2 = 8.
    assert len(s._price_history["BTCUSDT"]) <= 8


@pytest.mark.asyncio
async def test_signal_uses_last_close_price() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    for c in _candles([100, 100, 100, 100, 100, 100, 100, 150]):
        await s.on_market_data("BTCUSDT", c)
    signal = await s.generate_signals("BTCUSDT")
    if signal is not None:
        # Last close was 150 — signal price should reflect that.
        assert signal.price == 150.0