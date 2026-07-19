"""Fixed-parameter in-sample / out-of-sample SMA diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engine.backtest import BacktestResult, run_sma_backtest


@dataclass(frozen=True)
class InOutSampleResult:
    """Two contiguous, independently funded fixed-parameter backtests."""

    in_sample_size: int
    out_sample_size: int
    in_sample: BacktestResult
    out_sample: BacktestResult


def run_in_out_sample_sma_backtest(
    candles: list[dict[str, Any]],
    *,
    in_sample_size: int,
    short_window: int = 5,
    long_window: int = 20,
    initial_capital: float = 10_000.0,
    position_size_pct: float = 1.0,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0,
    max_volume_participation: float | None = None,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> InOutSampleResult:
    """Evaluate one fixed SMA configuration on contiguous in/out sample segments."""
    if short_window >= long_window:
        raise ValueError("short_window must be smaller than long_window")
    minimum_segment_size = long_window + 1
    if in_sample_size < minimum_segment_size:
        raise ValueError(f"in_sample_size must be at least {minimum_segment_size}")
    out_sample_size = len(candles) - in_sample_size
    if out_sample_size < minimum_segment_size:
        raise ValueError(
            f"out-of-sample segment must contain at least {minimum_segment_size} candles"
        )

    execution = {
        "initial_capital": initial_capital,
        "position_size_pct": position_size_pct,
        "fee_rate": fee_rate,
        "slippage_rate": slippage_rate,
        "max_volume_participation": max_volume_participation,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
    }
    return InOutSampleResult(
        in_sample_size=in_sample_size,
        out_sample_size=out_sample_size,
        in_sample=run_sma_backtest(
            candles[:in_sample_size],
            short_window=short_window,
            long_window=long_window,
            **execution,
        ),
        out_sample=run_sma_backtest(
            candles[in_sample_size:],
            short_window=short_window,
            long_window=long_window,
            **execution,
        ),
    )


__all__ = ["InOutSampleResult", "run_in_out_sample_sma_backtest"]
