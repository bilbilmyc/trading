"""Tests for RSI strategy module."""

from __future__ import annotations

from app.engine.rsi import compute_rsi, run_rsi_backtest


def test_rsi_returns_values_in_0_to_100() -> None:
    closes = [100 + i * 0.5 for i in range(30)]
    rsi = compute_rsi(closes, period=14)
    for v in rsi[14:]:
        assert 0.0 <= v <= 100.0


def test_rsi_high_for_strong_uptrend() -> None:
    closes = [100 + i for i in range(20)]
    rsi = compute_rsi(closes, period=14)
    assert rsi[-1] >= 70.0


def test_rsi_low_for_strong_downtrend() -> None:
    closes = [120 - i for i in range(20)]
    rsi = compute_rsi(closes, period=14)
    assert rsi[-1] <= 30.0


def test_rsi_handles_short_input() -> None:
    rsi = compute_rsi([100, 101, 102], period=14)
    assert rsi == [0.0, 0.0, 0.0]


def test_rsi_handles_constant_prices() -> None:
    closes = [100] * 30
    rsi = compute_rsi(closes, period=14)
    for v in rsi[14:]:
        assert v == 100.0


def test_rsi_backtest_flat_market_no_trades() -> None:
    from datetime import datetime

    candles = [
        {"close": 100, "open_time": datetime(2026, 1, 1), "open": 100, "high": 100, "low": 100, "volume": 1}
        for _ in range(50)
    ]
    result = run_rsi_backtest(candles)
    assert result.trades == 0


def test_rsi_backtest_too_short_returns_zero() -> None:
    from datetime import datetime

    candles = [
        {"close": 100, "open_time": datetime(2026, 1, 1), "open": 100, "high": 100, "low": 100, "volume": 1}
        for _ in range(5)
    ]
    result = run_rsi_backtest(candles)
    assert result.trades == 0
    assert len(result.equity_curve) == 5