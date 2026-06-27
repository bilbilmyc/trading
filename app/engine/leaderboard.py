"""Strategy leaderboard — rank strategies by performance.

Pulls trade outcomes from StrategyPerformanceTracker and produces a
ranked list. Ranking score = sharpe * 0.5 + (win_rate - 0.5) * 2 * 0.3
+ (1 - max_drawdown) * 0.2 — balanced for risk-adjusted return.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.engine.portfolio_metrics import PortfolioMetrics, compute_metrics
from app.engine.strategy_performance import StrategyPerformanceTracker


@dataclass
class LeaderboardEntry:
    rank: int
    strategy: str
    metrics: PortfolioMetrics
    score: float


def _score(metrics: PortfolioMetrics) -> float:
    """Composite ranking score in [0, ~3]."""
    sharpe_component = max(0.0, min(3.0, metrics.sharpe_ratio)) * 0.5
    winrate_component = max(0.0, min(1.0, metrics.win_rate)) * 0.3
    drawdown_component = max(0.0, 1.0 - metrics.max_drawdown) * 0.2
    return sharpe_component + winrate_component + drawdown_component


def build_leaderboard(tracker: StrategyPerformanceTracker) -> List[LeaderboardEntry]:
    """Build ranked leaderboard from trade outcomes.

    Returns strategies sorted by composite score (descending).
    """
    entries: List[LeaderboardEntry] = []
    for name in tracker.all_strategies():
        perf = tracker.performance(name)
        # Convert trade PnLs to a sequence of returns.
        # StrategyPerformanceTracker doesn't store individual outcomes yet
        # (it tracks aggregate metrics). For the leaderboard we use
        # aggregate equity_curve split into equal-sized deltas so the
        # metrics module can compute Sharpe / Sortino etc.
        if perf.equity_curve and len(perf.equity_curve) > 1:
            # Approximate per-period returns from equity curve.
            returns = [
                perf.equity_curve[i] - perf.equity_curve[i - 1]
                for i in range(1, len(perf.equity_curve))
            ]
            metrics = compute_metrics(returns)
        else:
            # Fallback: use expectancy as the only signal.
            metrics = PortfolioMetrics(
                sharpe_ratio=0.0, sortino_ratio=0.0,
                max_drawdown=0.0, max_drawdown_periods=0,
                profit_factor=perf.profit_factor,
                expectancy=perf.total_pnl / max(perf.trades, 1),
                win_rate=perf.winning_trades / max(perf.trades, 1),
                total_trades=perf.trades,
                winning_trades=perf.winning_trades,
                losing_trades=perf.losing_trades,
                average_win=perf.avg_win, average_loss=perf.avg_loss,
                max_consecutive_wins=0, max_consecutive_losses=0,
                annualized_return=0.0,
            )

        entries.append(LeaderboardEntry(
            rank=0,  # assigned after sort
            strategy=name,
            metrics=metrics,
            score=_score(metrics),
        ))

    # Sort by score descending.
    entries.sort(key=lambda e: e.score, reverse=True)
    for i, e in enumerate(entries):
        e.rank = i + 1
    return entries


__all__ = ["LeaderboardEntry", "build_leaderboard"]