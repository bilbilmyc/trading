"""Fixed-parameter rolling-window backtest diagnostics.

Each complete window is simulated from the same initial capital with the same
strategy parameters.  This is a local-performance study, not walk-forward
optimization: it neither selects parameters nor chains window equity into one
tradable portfolio.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

from app.engine.backtest import BacktestResult, run_sma_backtest

MAX_ROLLING_BACKTEST_WINDOWS = 128


@dataclass(frozen=True)
class RollingBacktestWindow:
    """One independently funded, fixed-parameter rolling backtest window."""

    window: int
    start_index: int
    end_index: int
    result: BacktestResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "result": {
                "initial_capital": self.result.initial_capital,
                "final_equity": self.result.final_equity,
                "total_pnl": self.result.total_pnl,
                "total_return_pct": self.result.total_return_pct,
                "trades": self.result.trades,
                "win_rate": self.result.win_rate,
                "max_drawdown": self.result.max_drawdown,
                "total_fees": self.result.total_fees,
                "gross_pnl": self.result.gross_pnl,
                "profit_factor": self.result.profit_factor,
            },
        }


@dataclass(frozen=True)
class RollingBacktestResult:
    """Descriptive summary of independently simulated rolling windows."""

    windows: list[RollingBacktestWindow]
    window_size: int
    step_size: int
    mean_total_return_pct: float
    return_stddev_pct: float
    profitable_window_ratio: float
    best_window_return_pct: float
    worst_window_return_pct: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "rolling": {
                "window_size": self.window_size,
                "step_size": self.step_size,
                "window_count": len(self.windows),
                "parameter_mode": "fixed",
                "capital_model": "independent_per_window",
                "max_window_count": MAX_ROLLING_BACKTEST_WINDOWS,
            },
            "summary": {
                "mean_total_return_pct": self.mean_total_return_pct,
                "return_stddev_pct": self.return_stddev_pct,
                "profitable_window_ratio": self.profitable_window_ratio,
                "best_window_return_pct": self.best_window_return_pct,
                "worst_window_return_pct": self.worst_window_return_pct,
            },
            "windows": [window.as_dict() for window in self.windows],
        }


def run_rolling_sma_backtest(
    candles: list[dict[str, Any]],
    *,
    window_size: int,
    step_size: int | None = None,
    short_window: int = 5,
    long_window: int = 20,
    initial_capital: float = 10_000.0,
    position_size_pct: float = 1.0,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0,
    max_volume_participation: float | None = None,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> RollingBacktestResult:
    """Run the same SMA configuration over bounded, complete rolling windows."""

    if window_size < 3:
        raise ValueError("window_size must be at least 3")
    step = window_size if step_size is None else step_size
    if step <= 0:
        raise ValueError("step_size must be positive")
    if short_window >= long_window:
        raise ValueError("short_window must be smaller than long_window")

    window_count = 1 + (len(candles) - window_size) // step if len(candles) >= window_size else 0
    if not window_count:
        raise ValueError("not enough candles for one complete rolling window")
    if window_count > MAX_ROLLING_BACKTEST_WINDOWS:
        raise ValueError(
            f"rolling request would create {window_count} windows; maximum is "
            f"{MAX_ROLLING_BACKTEST_WINDOWS}"
        )

    execution: dict[str, Any] = {
        "initial_capital": initial_capital,
        "position_size_pct": position_size_pct,
        "fee_rate": fee_rate,
        "slippage_rate": slippage_rate,
        "max_volume_participation": max_volume_participation,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
    }
    windows: list[RollingBacktestWindow] = []
    for start_index in range(0, len(candles) - window_size + 1, step):
        end_index = start_index + window_size - 1
        result = run_sma_backtest(
            candles[start_index : end_index + 1],
            short_window=short_window,
            long_window=long_window,
            **execution,
        )
        windows.append(
            RollingBacktestWindow(
                window=len(windows) + 1,
                start_index=start_index,
                end_index=end_index,
                result=result,
            )
        )

    returns = [window.result.total_return_pct for window in windows]
    mean_return = sum(returns) / len(returns)
    variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
    return RollingBacktestResult(
        windows=windows,
        window_size=window_size,
        step_size=step,
        mean_total_return_pct=round(mean_return, 4),
        return_stddev_pct=round(sqrt(variance), 4),
        profitable_window_ratio=round(sum(value > 0 for value in returns) / len(returns), 4),
        best_window_return_pct=round(max(returns), 4),
        worst_window_return_pct=round(min(returns), 4),
    )


__all__ = [
    "MAX_ROLLING_BACKTEST_WINDOWS",
    "RollingBacktestResult",
    "RollingBacktestWindow",
    "run_rolling_sma_backtest",
]
