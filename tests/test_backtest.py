"""Backtest engine — run SMA strategy on historical klines, compute PnL."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from app.engine.backtest import (
    BacktestResult,
    PortfolioStrategyConfig,
    run_multi_sma_backtest,
    run_sma_backtest,
)


def _candles(prices: list[float]) -> list[dict[str, Any]]:
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
    result = run_sma_backtest(
        _candles(prices), short_window=2, long_window=4, initial_capital=10_000
    )

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


def _custom_candles(rows: list[tuple[float, float, float, float]]) -> list[dict[str, Any]]:
    """Build candles as (open, high, low, close) tuples."""
    return [
        {
            "open_time": datetime(2026, 1, 1, 0, index, 0),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1.0,
        }
        for index, (open_price, high, low, close) in enumerate(rows)
    ]


def test_backtest_fills_signal_on_next_candle_open() -> None:
    """A close-based signal must not fill at the same candle's close."""
    candles = _custom_candles(
        [
            (10, 10, 10, 10),
            (10, 10, 10, 10),
            (10, 10, 10, 10),
            (20, 20, 20, 20),  # crossover is only known after this close
            (40, 40, 30, 30),  # next open is the first executable price
            (35, 35, 35, 35),
        ]
    )

    result = run_sma_backtest(
        candles,
        short_window=2,
        long_window=3,
        initial_capital=1_000,
        fee_rate=0,
    )

    assert result.trades == 1
    assert result.trade_history[0].entry_index == 4
    assert result.trade_history[0].entry_price == 40
    assert result.trade_history[0].exit_reason == "end_of_data"


def test_backtest_accounts_for_fees_and_slippage() -> None:
    candles = _custom_candles(
        [
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (110, 110, 110, 110),
            (120, 120, 115, 118),
            (125, 125, 125, 125),
        ]
    )

    frictionless = run_sma_backtest(candles, 2, 3, 1_000, fee_rate=0)
    realistic = run_sma_backtest(candles, 2, 3, 1_000, fee_rate=0.001, slippage_rate=0.002)

    assert realistic.total_fees > 0
    assert realistic.final_equity < frictionless.final_equity
    assert realistic.gross_pnl > realistic.total_pnl


def test_backtest_uses_protective_stop_when_stop_and_target_touch() -> None:
    candles = _custom_candles(
        [
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (110, 110, 110, 110),
            (100, 110, 90, 100),  # both +/- 5% levels are reachable
            (100, 100, 100, 100),
        ]
    )

    result = run_sma_backtest(
        candles,
        short_window=2,
        long_window=3,
        initial_capital=1_000,
        fee_rate=0,
        stop_loss_pct=0.05,
        take_profit_pct=0.05,
    )

    assert result.trades == 1
    trade = result.trade_history[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == 95
    assert trade.net_pnl < 0


def test_backtest_rejects_invalid_ohlc_data() -> None:
    candles = _candles([100, 100, 100, 100])
    candles[2]["low"] = 105

    with pytest.raises(ValueError, match="inconsistent OHLC"):
        run_sma_backtest(candles, short_window=2, long_window=3)


def test_backtest_fills_stop_at_open_when_price_gaps_below_trigger() -> None:
    candles = _custom_candles(
        [
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (110, 110, 110, 110),
            (100, 101, 99, 100),
            (80, 85, 75, 80),  # position cannot sell at the 95 stop after this gap
        ]
    )

    result = run_sma_backtest(
        candles,
        short_window=2,
        long_window=3,
        initial_capital=1_000,
        fee_rate=0,
        stop_loss_pct=0.05,
    )

    assert result.trade_history[0].exit_reason == "stop_loss"
    assert result.trade_history[0].exit_price == 80


def test_multi_strategy_backtest_aggregates_independently_allocated_equity() -> None:
    candles = _candles([100, 100, 101, 103, 106, 108, 104, 100, 98, 101, 105, 109])
    strategies = [
        PortfolioStrategyConfig(name="fast", short_window=2, long_window=4, weight=0.6),
        PortfolioStrategyConfig(name="slow", short_window=3, long_window=5, weight=0.4),
    ]

    result = run_multi_sma_backtest(candles, strategies, initial_capital=10_000, fee_rate=0)

    assert result.initial_capital == 10_000
    assert len(result.strategies) == 2
    assert len(result.equity_curve) == len(candles)
    assert result.final_equity == round(
        sum(item.result.final_equity for item in result.strategies), 4
    )
    assert result.equity_curve[-1] == result.final_equity
    assert [item.allocated_capital for item in result.strategies] == [6000.0, 4000.0]


def test_multi_strategy_backtest_rejects_incomplete_or_duplicate_allocations() -> None:
    candles = _candles([100] * 8)

    with pytest.raises(ValueError, match="sum to 1.0"):
        run_multi_sma_backtest(
            candles,
            [
                PortfolioStrategyConfig(name="one", short_window=2, long_window=4, weight=0.4),
                PortfolioStrategyConfig(name="two", short_window=3, long_window=5, weight=0.4),
            ],
        )
    with pytest.raises(ValueError, match="duplicate"):
        run_multi_sma_backtest(
            candles,
            [
                PortfolioStrategyConfig(name="same", short_window=2, long_window=4, weight=0.5),
                PortfolioStrategyConfig(name="SAME", short_window=3, long_window=5, weight=0.5),
            ],
        )
