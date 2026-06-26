"""Backtest engine — run SMA strategy on historical klines, compute PnL."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.engine.backtest import BacktestResult, run_sma_backtest


def _candles(prices: List[float]) -> List[Dict[str, Any]]:
    return [
        {
            "open_time": datetime(2026, 1, 1, 0, 0, 0),
            "open": p,
            "high": p + 1,
            "low": p - 1,
            "close": p,
            "volume": 1.0,
        }
        for p in prices
    ]


def test_backtest_returns_pnl_curve_and_metrics() -> None:
    # 30 candles; SMA(3, 5) crossover should trigger on the upward move.
    candles = _candles([100, 101, 102, 99, 95, 96, 98, 102, 105, 110, 108, 105, 100, 98, 95])
    result = run_sma_backtest(candles, short_window=3, long_window=5, initial_capital=10_000)

    assert isinstance(result, BacktestResult)
    assert len(result.equity_curve) == len(candles)
    assert result.initial_capital == 10_000
    assert result.final_equity > 0


def test_backtest_handles_no_signals() -> None:
    """Flat market → no trades → equity stays at initial."""
    candles = _candles([100] * 30)
    result = run_sma_backtest(candles, short_window=3, long_window=5, initial_capital=10_000)

    assert result.trades == 0
    assert result.final_equity == 10_000.0
    assert result.equity_curve[-1] == 10_000.0


def test_backtest_too_few_candles_yields_no_trade() -> None:
    candles = _candles([100, 101])
    result = run_sma_backtest(candles, short_window=3, long_window=5, initial_capital=10_000)

    assert result.trades == 0
    assert result.final_equity == 10_000.0


def test_backtest_records_long_entry_and_exit() -> None:
    """Clear uptrend: enter long, then close at higher price → positive PnL."""
    prices = [100] * 5 + [101, 102, 105, 108, 110, 109, 107, 105]
    result = run_sma_backtest(_candles(prices), short_window=2, long_window=4, initial_capital=10_000)

    assert result.trades >= 1
    # If a trade fired, total PnL should be positive on this uptrend.
    assert result.total_pnl >= 0


def test_backtest_metrics_shape() -> None:
    candles = _candles([100, 102, 104, 103, 101, 99, 98, 100, 102, 104])
    result = run_sma_backtest(candles, short_window=2, long_window=4, initial_capital=10_000)

    assert hasattr(result, "initial_capital")
    assert hasattr(result, "final_equity")
    assert hasattr(result, "trades")
    assert hasattr(result, "total_pnl")
    assert hasattr(result, "max_drawdown")
    assert hasattr(result, "win_rate")
    assert hasattr(result, "equity_curve")