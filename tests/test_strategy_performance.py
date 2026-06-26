"""Tests for StrategyPerformanceTracker."""

from __future__ import annotations

from app.engine.strategy_performance import (
    StrategyPerformanceTracker,
    TradeOutcome,
)


def _trade(strategy: str, pnl: float, t: float = 1.0) -> TradeOutcome:
    return TradeOutcome(
        strategy=strategy,
        symbol="BTCUSDT",
        side="long",
        entry_price=100.0,
        exit_price=100.0 + pnl,
        quantity=1.0,
        pnl=pnl,
        opened_at=t,
        closed_at=t,
    )


def test_empty_strategy_returns_zero_metrics() -> None:
    t = StrategyPerformanceTracker()
    p = t.performance("nonexistent")
    assert p.total_trades == 0
    assert p.win_rate == 0.0
    assert p.equity_curve == [10_000.0]


def test_records_only_specified_strategy() -> None:
    t = StrategyPerformanceTracker()
    t.record(_trade("sma_a", 100))
    t.record(_trade("sma_b", -50))
    p_a = t.performance("sma_a")
    p_b = t.performance("sma_b")
    assert p_a.total_trades == 1
    assert p_b.total_trades == 1
    assert p_a.total_pnl == 100
    assert p_b.total_pnl == -50


def test_win_rate_calculation() -> None:
    t = StrategyPerformanceTracker()
    t.record(_trade("s", 100, 1))
    t.record(_trade("s", -50, 2))
    t.record(_trade("s", 200, 3))
    t.record(_trade("s", -30, 4))
    p = t.performance("s")
    assert p.winning_trades == 2
    assert p.losing_trades == 2
    assert p.win_rate == 0.5


def test_avg_win_and_avg_loss() -> None:
    t = StrategyPerformanceTracker()
    t.record(_trade("s", 100, 1))
    t.record(_trade("s", 200, 2))
    t.record(_trade("s", -50, 3))
    p = t.performance("s")
    assert p.avg_win == 150.0
    assert p.avg_loss == -50.0


def test_profit_factor_no_losses_is_infinity() -> None:
    t = StrategyPerformanceTracker()
    t.record(_trade("s", 100))
    t.record(_trade("s", 200))
    p = t.performance("s")
    # profit_factor is rounded to 9999.99 sentinel for infinity.
    assert p.profit_factor == 9999.99


def test_profit_factor_balanced() -> None:
    t = StrategyPerformanceTracker()
    t.record(_trade("s", 100))
    t.record(_trade("s", -100))
    p = t.performance("s")
    assert p.profit_factor == 1.0


def test_equity_curve_includes_initial_capital() -> None:
    t = StrategyPerformanceTracker()
    t.record(_trade("s", 100, 1))
    t.record(_trade("s", 50, 2))
    p = t.performance("s", initial_capital=10_000.0)
    # First point is initial; then each trade appends.
    assert p.equity_curve[0] == 10_000.0
    assert p.equity_curve[-1] == 10_150.0


def test_max_drawdown_detects_peak_to_trough() -> None:
    t = StrategyPerformanceTracker()
    # Sequence: +500, +500, -800 → peak 11_000, trough 10_200 → dd 800/11_000 ≈ 7.27%
    t.record(_trade("s", 500, 1))
    t.record(_trade("s", 500, 2))
    t.record(_trade("s", -800, 3))
    p = t.performance("s")
    assert abs(p.max_drawdown - 800 / 11_000) < 0.001


def test_all_strategies_returns_unique_names() -> None:
    t = StrategyPerformanceTracker()
    t.record(_trade("alpha", 100))
    t.record(_trade("beta", -50))
    t.record(_trade("alpha", 200))
    t.record(_trade("gamma", 30))
    assert t.all_strategies() == ["alpha", "beta", "gamma"]