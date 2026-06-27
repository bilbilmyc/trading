"""Walk-forward analysis — optimize on in-sample, test on out-of-sample.

Classic technique for validating strategy robustness:
1. Split history into N rolling windows.
2. For each window: optimize params on the train portion.
3. Run the best params on the test portion.
4. Aggregate OOS performance.

This module provides the scaffolding — `optimize_fn` is a callable the
caller supplies (could be grid search, Bayesian, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

from app.engine.rsi import run_rsi_backtest
from app.engine.backtest import run_sma_backtest


@dataclass
class WalkForwardWindow:
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    best_params: dict
    in_sample_metrics: dict
    out_of_sample_metrics: dict


@dataclass
class WalkForwardResult:
    windows: List[WalkForwardWindow] = field(default_factory=list)
    aggregate_oos_pnl: float = 0.0
    aggregate_oos_sharpe: float = 0.0
    aggregate_oos_win_rate: float = 0.0
    aggregate_max_dd: float = 0.0


def _sharpe(returns: Sequence[float]) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return mean / (var ** 0.5) if var > 0 else 0.0


def _max_dd(equity: Sequence[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _equity_returns(equity: Sequence[float]) -> List[float]:
    if len(equity) < 2:
        return []
    return [equity[i] - equity[i - 1] for i in range(1, len(equity))]


def walk_forward_sma(
    candles: Sequence[dict],
    *,
    train_pct: float = 0.7,
    n_windows: int = 4,
    short_candidates: Sequence[int] = (3, 5, 8, 13),
    long_candidates: Sequence[int] = (10, 15, 20, 30),
    initial_capital: float = 10_000.0,
) -> WalkForwardResult:
    """Walk-forward SMA strategy: rolling in-sample / out-of-sample split.

    For each window: pick the SMA(short, long) combo with the highest
    in-sample total PnL, then evaluate it on the OOS portion.
    """
    if not candles or len(candles) < 30:
        return WalkForwardResult()

    n = len(candles)
    window_size = n // n_windows
    if window_size < 20:
        return WalkForwardResult()

    result = WalkForwardResult()
    total_oos_returns: List[float] = []
    win_count = 0
    max_dd_peak = 0.0
    running_equity = initial_capital
    equity_curve: List[float] = [initial_capital]

    for w in range(n_windows):
        win_start = w * window_size
        win_end = win_start + window_size
        if win_end > n:
            break
        train_end = win_start + int(window_size * train_pct)
        train = candles[win_start:train_end]
        test = candles[train_end:win_end]
        if len(train) < 20 or len(test) < 3:
            continue

        # Grid search for best params on train.
        best_pnl = float("-inf")
        best_params = {}
        for short_w in short_candidates:
            for long_w in long_candidates:
                if short_w >= long_w:
                    continue
                r = run_sma_backtest(
                    train,
                    short_window=short_w,
                    long_window=long_w,
                    initial_capital=initial_capital,
                )
                if r.total_pnl > best_pnl:
                    best_pnl = r.total_pnl
                    best_params = {"short_window": short_w, "long_window": long_w}

        # Evaluate on OOS.
        oos_r = run_sma_backtest(
            test,
            short_window=best_params.get("short_window", 5),
            long_window=best_params.get("long_window", 20),
            initial_capital=initial_capital,
        )
        in_sample_r = run_sma_backtest(
            train,
            short_window=best_params.get("short_window", 5),
            long_window=best_params.get("long_window", 20),
            initial_capital=initial_capital,
        )

        result.windows.append(
            WalkForwardWindow(
                train_start=win_start,
                train_end=train_end,
                test_start=train_end,
                test_end=win_end,
                best_params=best_params,
                in_sample_metrics={"total_pnl": in_sample_r.total_pnl, "trades": in_sample_r.trades},
                out_of_sample_metrics={"total_pnl": oos_r.total_pnl, "trades": oos_r.trades},
            )
        )

        # Aggregate.
        total_oos_returns.extend(_equity_returns(oos_r.equity_curve))
        if oos_r.total_pnl > 0:
            win_count += 1
        running_equity += oos_r.total_pnl
        equity_curve.append(running_equity)
        if oos_r.max_drawdown > max_dd_peak:
            max_dd_peak = oos_r.max_drawdown

    result.aggregate_oos_pnl = sum(w.out_of_sample_metrics["total_pnl"] for w in result.windows)
    result.aggregate_oos_sharpe = _sharpe(total_oos_returns)
    result.aggregate_oos_win_rate = win_count / len(result.windows) if result.windows else 0.0
    result.aggregate_max_dd = max_dd_peak
    return result


__all__ = ["WalkForwardWindow", "WalkForwardResult", "walk_forward_sma"]