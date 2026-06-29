"""Strategy performance tracker — equity curve, win rate, PnL per strategy.

Records each trade outcome (open + close) into an in-memory ledger.
Returns aggregated metrics. Used by /api/v1/strategies/{name}/performance
and a future dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TradeOutcome:
    strategy: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    opened_at: float
    closed_at: float


@dataclass
class StrategyPerformance:
    strategy: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float          # |sum(wins)| / |sum(losses)|
    max_drawdown: float
    equity_curve: list[float] = field(default_factory=list)


class StrategyPerformanceTracker:
    """Per-strategy performance ledger.

    Equity curve is reconstructed by replaying trades in chronological
    order; we don't snapshot intermediate equity. Good enough for a
    strategy-level summary; not a full position state machine.
    """

    def __init__(self) -> None:
        self._trades: list[TradeOutcome] = []

    def record(self, outcome: TradeOutcome) -> None:
        self._trades.append(outcome)

    def for_strategy(self, strategy: str) -> list[TradeOutcome]:
        return [t for t in self._trades if t.strategy == strategy]

    def all_strategies(self) -> list[str]:
        return sorted({t.strategy for t in self._trades})

    def performance(
        self,
        strategy: str,
        initial_capital: float = 10_000.0,
    ) -> StrategyPerformance:
        trades = self.for_strategy(strategy)
        if not trades:
            return StrategyPerformance(
                strategy=strategy,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                profit_factor=0.0,
                max_drawdown=0.0,
                equity_curve=[initial_capital],
            )

        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl < 0]
        total_pnl = sum(t.pnl for t in trades)
        win_rate = len(wins) / len(trades) if trades else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        profit_factor = (
            abs(sum(wins)) / abs(sum(losses)) if losses else float("inf")
        )

        # Build equity curve by replaying trades sorted by close time.
        sorted_trades = sorted(trades, key=lambda t: t.closed_at)
        equity = initial_capital
        curve = [equity]
        peak = equity
        max_dd = 0.0
        for t in sorted_trades:
            equity += t.pnl
            curve.append(equity)
            peak = max(peak, equity)
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd

        return StrategyPerformance(
            strategy=strategy,
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=round(win_rate, 4),
            total_pnl=round(total_pnl, 4),
            avg_win=round(avg_win, 4),
            avg_loss=round(avg_loss, 4),
            profit_factor=round(profit_factor, 4) if profit_factor != float("inf") else 9999.99,
            max_drawdown=round(max_dd, 4),
            equity_curve=[round(e, 4) for e in curve],
        )


__all__ = ["TradeOutcome", "StrategyPerformance", "StrategyPerformanceTracker"]
