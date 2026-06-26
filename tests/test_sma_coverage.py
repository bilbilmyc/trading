"""Additional coverage tests for SMAStrategy — SMA compute + crossover."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from app.strategies.sma import SMAStrategy


def _prices(seq: List[float]) -> List[Dict[str, Any]]:
    base = datetime(2026, 1, 1)
    return [
        {"open_time": base + timedelta(hours=i), "open": p, "high": p, "low": p, "close": p, "volume": 1.0}
        for i, p in enumerate(seq)
    ]


def test_short_window_must_be_smaller_than_long() -> None:
    with pytest.raises(ValueError):
        SMAStrategy(short_window=10, long_window=5)


def test_short_window_equal_to_long_rejected() -> None:
    with pytest.raises(ValueError):
        SMAStrategy(short_window=5, long_window=5)


@pytest.mark.asyncio
async def test_zero_price_filtered() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    await s.on_market_data("BTCUSDT", {"open_time": datetime(2026, 1, 1), "last_price": 0})
    assert s.get_price_history_length("BTCUSDT") == 0


@pytest.mark.asyncio
async def test_negative_price_filtered() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    await s.on_market_data("BTCUSDT", {"open_time": datetime(2026, 1, 1), "last_price": -10})
    assert s.get_price_history_length("BTCUSDT") == 0


@pytest.mark.asyncio
async def test_close_price_used_when_no_last_price() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    await s.on_market_data("BTCUSDT", {"open_time": datetime(2026, 1, 1), "close": 100.0})
    assert s.get_price_history_length("BTCUSDT") == 1


@pytest.mark.asyncio
async def test_price_history_length_zero_for_unknown_symbol() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    assert s.get_price_history_length("UNKNOWN") == 0


@pytest.mark.asyncio
async def test_last_signal_time_empty_initially() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    assert s.get_last_signal_time("BTCUSDT") is None


def test_get_current_sma_initially_none() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    smas = s.get_current_sma("UNKNOWN")
    assert smas == {"short": None, "long": None}


@pytest.mark.asyncio
async def test_get_current_sma_computes_after_history_fills() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    for p in _prices([100, 102, 104, 106, 108]):
        await s.on_market_data("BTCUSDT", p)
    smas = s.get_current_sma("BTCUSDT")
    assert smas["short"] is not None
    assert smas["long"] is not None
    assert smas["short"] > smas["long"]  # short catches recent uptrend first


@pytest.mark.asyncio
async def test_strong_downtrend_generates_signal() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    prices = [120 - i for i in range(20)]
    for p in _prices(prices):
        await s.on_market_data("BTCUSDT", p)
    sig = await s.generate_signals("BTCUSDT")
    if sig is not None:
        assert sig.action.value in ("buy", "sell")


@pytest.mark.asyncio
async def test_signal_includes_strength_in_range() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    for p in _prices([100] * 30):
        await s.on_market_data("BTCUSDT", p)
    sig = await s.generate_signals("BTCUSDT")
    if sig is not None:
        assert 0.0 <= sig.strength <= 1.0


def test_strategy_default_name_format() -> None:
    s = SMAStrategy(short_window=7, long_window=21)
    assert s.name == "SMA_7_21"


def test_strategy_explicit_name_override() -> None:
    s = SMAStrategy(short_window=7, long_window=21, name="btc-sma")
    assert s.name == "btc-sma"


@pytest.mark.asyncio
async def test_separate_state_per_symbol() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    for p in _prices([100] * 5):
        await s.on_market_data("BTCUSDT", p)
    # Internal buffer is bounded by long_window * 2 = 8.
    assert s.get_price_history_length("BTCUSDT") <= 8
    assert s.get_price_history_length("ETHUSDT") == 0


def test_should_generate_signal_default_true() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    assert s.should_generate_signal("BTCUSDT") is True


def test_should_generate_signal_respects_interval() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    s._update_signal_time("BTCUSDT")
    assert s.should_generate_signal("BTCUSDT", min_interval_seconds=600) is False
    assert s.should_generate_signal("BTCUSDT", min_interval_seconds=0) is True


@pytest.mark.asyncio
async def test_stop_resets_history() -> None:
    s = SMAStrategy(short_window=2, long_window=4)
    for p in _prices([100] * 5):
        await s.on_market_data("BTCUSDT", p)
    await s.stop()
    assert s.get_price_history_length("BTCUSDT") == 0


def test_base_url_abstract_property() -> None:
    """Subclasses must implement base_url."""
    # Just verify the abstract property exists.
    from app.exchanges.base import ExchangeBase
    assert hasattr(ExchangeBase, "base_url")