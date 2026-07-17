"""Strategy-governance primitives: walk-forward validation and paper evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from typing import Any

from app.engine.backtest import BacktestResult, run_sma_backtest


@dataclass(frozen=True)
class SMAParameters:
    """One candidate configuration considered inside a training window."""

    short_window: int
    long_window: int


@dataclass(frozen=True)
class WalkForwardFold:
    """A single strictly out-of-sample walk-forward fold."""

    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    selected_parameters: SMAParameters
    train_return_pct: float
    train_max_drawdown: float
    out_of_sample: BacktestResult

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["out_of_sample"] = _backtest_payload(self.out_of_sample)
        return payload


@dataclass(frozen=True)
class WalkForwardResult:
    """Aggregate of only the out-of-sample segments from a WFO run."""

    folds: list[WalkForwardFold]
    initial_capital: float
    final_equity: float
    total_pnl: float
    total_return_pct: float
    trades: int
    win_rate: float
    max_drawdown: float
    total_fees: float
    profitable_fold_ratio: float
    return_stddev_pct: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "folds": [fold.as_dict() for fold in self.folds],
            "initial_capital": self.initial_capital,
            "final_equity": self.final_equity,
            "total_pnl": self.total_pnl,
            "total_return_pct": self.total_return_pct,
            "trades": self.trades,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "total_fees": self.total_fees,
            "profitable_fold_ratio": self.profitable_fold_ratio,
            "return_stddev_pct": self.return_stddev_pct,
        }


def _backtest_payload(result: BacktestResult) -> dict[str, Any]:
    """Compact result for audit JSON; no in-sample curve is persisted."""

    return {
        "initial_capital": result.initial_capital,
        "final_equity": result.final_equity,
        "total_pnl": result.total_pnl,
        "total_return_pct": result.total_return_pct,
        "trades": result.trades,
        "win_rate": result.win_rate,
        "max_drawdown": result.max_drawdown,
        "total_fees": result.total_fees,
        "gross_pnl": result.gross_pnl,
        "profit_factor": result.profit_factor,
    }


def _select_candidate(
    candles: list[dict[str, Any]], candidates: list[SMAParameters], execution: dict[str, Any]
) -> tuple[SMAParameters, BacktestResult]:
    trials: list[tuple[SMAParameters, BacktestResult]] = []
    for candidate in candidates:
        trial = run_sma_backtest(
            candles,
            short_window=candidate.short_window,
            long_window=candidate.long_window,
            **execution,
        )
        trials.append((candidate, trial))

    # Prefer return, then lower drawdown, then a larger sample of closed trades.
    return max(
        trials,
        key=lambda item: (item[1].total_return_pct, -item[1].max_drawdown, item[1].trades),
    )


def run_walk_forward_backtest(
    candles: list[dict[str, Any]],
    *,
    train_size: int,
    test_size: int,
    step_size: int | None = None,
    candidate_parameters: list[SMAParameters] | None = None,
    short_window: int = 5,
    long_window: int = 20,
    initial_capital: float = 10_000.0,
    position_size_pct: float = 1.0,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> WalkForwardResult:
    """Run an expanding-window walk-forward test without parameter look-ahead.

    Parameter choice is made on each training segment only. The selected pair
    is then executed from scratch on the following test segment, so aggregate
    values are entirely out-of-sample evidence rather than optimized results.
    """

    if train_size < 3 or test_size < 3:
        raise ValueError("train_size and test_size must be at least 3")
    step = step_size or test_size
    if step <= 0:
        raise ValueError("step_size must be positive")

    candidates = candidate_parameters or [
        SMAParameters(short_window=short_window, long_window=long_window)
    ]
    if not candidates:
        raise ValueError("candidate_parameters cannot be empty")
    for candidate in candidates:
        if candidate.short_window <= 0 or candidate.long_window <= candidate.short_window:
            raise ValueError("each candidate must have short_window < long_window")

    execution = {
        "initial_capital": initial_capital,
        "position_size_pct": position_size_pct,
        "fee_rate": fee_rate,
        "slippage_rate": slippage_rate,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
    }
    folds: list[WalkForwardFold] = []
    start = 0
    while start + train_size + test_size <= len(candles):
        train_end = start + train_size
        test_end = train_end + test_size
        selected, train_result = _select_candidate(candles[start:train_end], candidates, execution)
        oos_result = run_sma_backtest(
            candles[train_end:test_end],
            short_window=selected.short_window,
            long_window=selected.long_window,
            **execution,
        )
        folds.append(
            WalkForwardFold(
                fold=len(folds) + 1,
                train_start=start,
                train_end=train_end - 1,
                test_start=train_end,
                test_end=test_end - 1,
                selected_parameters=selected,
                train_return_pct=train_result.total_return_pct,
                train_max_drawdown=train_result.max_drawdown,
                out_of_sample=oos_result,
            )
        )
        start += step

    if not folds:
        raise ValueError("not enough candles for one train/test walk-forward fold")

    equity = initial_capital
    returns = [fold.out_of_sample.total_return_pct for fold in folds]
    total_trades = sum(fold.out_of_sample.trades for fold in folds)
    weighted_wins = sum(fold.out_of_sample.win_rate * fold.out_of_sample.trades for fold in folds)
    for fold in folds:
        equity *= fold.out_of_sample.final_equity / initial_capital
    mean_return = sum(returns) / len(returns)
    variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)

    return WalkForwardResult(
        folds=folds,
        initial_capital=round(initial_capital, 4),
        final_equity=round(equity, 4),
        total_pnl=round(equity - initial_capital, 4),
        total_return_pct=round((equity / initial_capital - 1) * 100, 4),
        trades=total_trades,
        win_rate=round(weighted_wins / total_trades, 4) if total_trades else 0.0,
        max_drawdown=round(max(fold.out_of_sample.max_drawdown for fold in folds), 4),
        total_fees=round(sum(fold.out_of_sample.total_fees for fold in folds), 4),
        profitable_fold_ratio=round(sum(value > 0 for value in returns) / len(returns), 4),
        return_stddev_pct=round(sqrt(variance), 4),
    )


__all__ = [
    "SMAParameters",
    "WalkForwardFold",
    "WalkForwardResult",
    "run_walk_forward_backtest",
]
