"""Portfolio analytics — risk-adjusted performance metrics.

Standard quant metrics for a series of period returns:
  - Sharpe ratio  : mean / std (assumes rf=0 by default)
  - Sortino ratio : mean / downside_deviation
  - Max drawdown  : peak-to-trough decline
  - Max DD period : time-from-peak-to-recovery (in periods)
  - Profit factor : sum(wins) / |sum(losses)|
  - Expectancy    : avg PnL per trade
  - Win rate      : wins / total

Inputs accept either a list of per-trade PnLs or a list of period
returns. Pure functions, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


@dataclass
class PortfolioMetrics:
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float          # 0..1
    max_drawdown_periods: int    # # of periods from peak to recovery (or now)
    profit_factor: float
    expectancy: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    average_win: float
    average_loss: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    annualized_return: float     # simple annualization: mean * periods_per_year


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: Sequence[float], mean: Optional[float] = None) -> float:
    if len(values) < 2:
        return 0.0
    m = mean if mean is not None else _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _consecutive_runs(values: Sequence[float]) -> tuple:
    """Return (max_consecutive_wins, max_consecutive_losses)."""
    max_w = max_l = 0
    cur_w = cur_l = 0
    for v in values:
        if v > 0:
            cur_w += 1
            cur_l = 0
            max_w = max(max_w, cur_w)
        elif v < 0:
            cur_l += 1
            cur_w = 0
            max_l = max(max_l, cur_l)
        else:
            cur_w = cur_l = 0
    return max_w, max_l


def _max_drawdown_periods(equity_curve: Sequence[float]) -> tuple:
    """Return (max_dd_fraction, max_dd_periods)."""
    if not equity_curve:
        return 0.0, 0
    peak = equity_curve[0]
    max_dd = 0.0
    max_dd_periods = 0
    current_dd_start = 0
    for i, equity in enumerate(equity_curve):
        if equity > peak:
            peak = equity
            current_dd_start = i
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_periods = i - current_dd_start
    return max_dd, max_dd_periods


def compute_metrics(
    trade_pnls: Sequence[float],
    equity_curve: Optional[Sequence[float]] = None,
    periods_per_year: int = 252,
) -> PortfolioMetrics:
    """Compute all portfolio metrics in one pass.

    trade_pnls: list of per-trade P&L (or per-period returns).
    equity_curve: optional running total. If absent, derived from cumulative
    sum of trade_pnls starting at 0.

    periods_per_year: for annualization (default 252 = daily trading days).
    """
    pnls = list(trade_pnls)
    n = len(pnls)
    if n == 0 and equity_curve is None:
        return PortfolioMetrics(
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown=0.0,
            max_drawdown_periods=0,
            profit_factor=0.0,
            expectancy=0.0,
            win_rate=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            average_win=0.0,
            average_loss=0.0,
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            annualized_return=0.0,
        )

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = n_wins / n if n else 0.0
    avg_win = _mean(wins)
    avg_loss = _mean(losses) if losses else 0.0

    # Profit factor: |sum(wins)| / |sum(losses)|. 0 if no losses.
    if losses:
        profit_factor = abs(sum(wins)) / abs(sum(losses))
    else:
        profit_factor = float("inf") if wins else 0.0
        if profit_factor == float("inf"):
            # Use a large sentinel for downstream serialization.
            profit_factor = 9999.0

    expectancy = _mean(pnls)
    mean_ret = _mean(pnls)
    std_ret = _std(pnls, mean_ret)

    # Sortino: downside deviation = sqrt(mean(min(r, 0)^2))
    downside = [min(p, 0.0) ** 2 for p in pnls]
    downside_dev = math.sqrt(_mean(downside))
    if downside_dev > 0:
        sortino = mean_ret / downside_dev
    else:
        sortino = 0.0

    # Sharpe (rf=0). Avoid div-by-zero.
    if std_ret > 0:
        sharpe = mean_ret / std_ret
    else:
        sharpe = 0.0

    # Annualized return: simple (no compounding).
    annualized = mean_ret * periods_per_year

    # Equity curve for drawdown.
    if equity_curve is None:
        equity_curve = []
        running = 0.0
        for p in pnls:
            running += p
            equity_curve.append(running)
    max_dd, max_dd_periods = _max_drawdown_periods(equity_curve)

    # Consecutive runs.
    max_w_run, max_l_run = _consecutive_runs(pnls)

    return PortfolioMetrics(
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        max_drawdown=round(max_dd, 4),
        max_drawdown_periods=max_dd_periods,
        profit_factor=round(profit_factor, 4) if profit_factor != float("inf") else 9999.0,
        expectancy=round(expectancy, 4),
        win_rate=round(win_rate, 4),
        total_trades=n,
        winning_trades=n_wins,
        losing_trades=n_losses,
        average_win=round(avg_win, 4),
        average_loss=round(avg_loss, 4),
        max_consecutive_wins=max_w_run,
        max_consecutive_losses=max_l_run,
        annualized_return=round(annualized, 4),
    )


__all__ = ["PortfolioMetrics", "compute_metrics"]