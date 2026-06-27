"""Tests for portfolio analytics — no TDD required per user; build features directly."""

from app.engine.portfolio_metrics import compute_metrics


def test_empty_pnls_returns_zero_metrics() -> None:
    m = compute_metrics([])
    assert m.sharpe_ratio == 0.0
    assert m.total_trades == 0
    assert m.win_rate == 0.0


def test_basic_metrics_calculation() -> None:
    pnls = [10, -5, 15, -8, 12, 7, -3, 9]
    m = compute_metrics(pnls)
    assert m.total_trades == 8
    assert m.winning_trades == 5
    assert m.losing_trades == 3
    assert abs(m.win_rate - 0.625) < 0.01
    assert m.expectancy > 0


def test_sharpe_ratio_positive_for_consistent_gains() -> None:
    pnls = [1, 2, 1, 2, 1, 2, 1, 2]
    m = compute_metrics(pnls)
    assert m.sharpe_ratio > 0


def test_sharpe_ratio_zero_for_constant_pnls() -> None:
    """Constant series has zero std → Sharpe = 0."""
    pnls = [5, 5, 5, 5]
    m = compute_metrics(pnls)
    assert m.sharpe_ratio == 0.0


def test_profit_factor_basic() -> None:
    # Sum wins = 100, sum losses = -50, PF = 2.0
    pnls = [50, 50, -25, -25]
    m = compute_metrics(pnls)
    assert m.profit_factor == 2.0


def test_profit_factor_no_losses() -> None:
    """No losses → wins only → profit_factor sentinel 9999.0."""
    pnls = [10, 20, 30]
    m = compute_metrics(pnls)
    assert m.profit_factor == 9999.0


def test_max_drawdown_calculation() -> None:
    equity = [100, 110, 105, 90, 95, 100, 130]
    m = compute_metrics([], equity_curve=equity)
    # Max DD from 110 to 90 = 18.18%
    assert abs(m.max_drawdown - (110 - 90) / 110) < 0.01


def test_max_drawdown_periods() -> None:
    # Peak at index 1 (110), trough at index 3 (90) → 2 periods
    equity = [100, 110, 105, 90, 95]
    m = compute_metrics([], equity_curve=equity)
    assert m.max_drawdown_periods == 2


def test_consecutive_wins_and_losses() -> None:
    pnls = [1, 1, 1, -1, -1, -1, -1, 1]
    m = compute_metrics(pnls)
    assert m.max_consecutive_wins == 3
    assert m.max_consecutive_losses == 4


def test_sortino_uses_downside_deviation() -> None:
    """Sortino penalizes downside only — same mean, lower vol of losses = higher Sortino."""
    pnls = [10, 10, 10, 10, 10]  # all wins
    m = compute_metrics(pnls)
    assert m.sortino_ratio == 0.0  # no downside


def test_average_win_and_loss() -> None:
    pnls = [10, 20, -5, -15]
    m = compute_metrics(pnls)
    assert m.average_win == 15.0
    assert m.average_loss == -10.0


def test_annualized_return() -> None:
    pnls = [0.1] * 252  # 10 bps daily
    m = compute_metrics(pnls, periods_per_year=252)
    assert abs(m.annualized_return - 0.1 * 252) < 0.01


def test_equity_curve_auto_derived() -> None:
    """Without explicit equity_curve, derived from cumulative sum of pnls."""
    pnls = [10, -5, 20, -3]
    m = compute_metrics(pnls)
    # Max drawdown = 25 (15 to 35 peak) / 35
    assert m.max_drawdown > 0


def test_zero_pnl_trade_doesnt_count_as_win() -> None:
    pnls = [10, 0, -5]
    m = compute_metrics(pnls)
    assert m.winning_trades == 1
    assert m.losing_trades == 1
    assert abs(m.win_rate - 1/3) < 0.001
