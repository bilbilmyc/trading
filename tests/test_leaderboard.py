from app.engine.leaderboard import build_leaderboard
from app.engine.strategy_performance import (
    StrategyPerformanceTracker,
    TradeOutcome,
)


def _win_outcome(i: int) -> TradeOutcome:
    return TradeOutcome(
        strategy="s_a", symbol="BTCUSDT", side="long",
        entry_price=100.0, exit_price=110.0, quantity=1.0,
        pnl=10.0, opened_at=float(i), closed_at=float(i),
    )


def _loss_outcome(i: int) -> TradeOutcome:
    return TradeOutcome(
        strategy="s_b", symbol="BTCUSDT", side="long",
        entry_price=100.0, exit_price=95.0, quantity=1.0,
        pnl=-5.0, opened_at=float(i), closed_at=float(i),
    )


def test_empty_tracker_yields_empty_leaderboard() -> None:
    t = StrategyPerformanceTracker()
    assert build_leaderboard(t) == []


def test_single_strategy_ranked_first() -> None:
    t = StrategyPerformanceTracker()
    t.record(_win_outcome(1))
    t.record(_win_outcome(2))
    board = build_leaderboard(t)
    assert len(board) == 1
    assert board[0].rank == 1
    assert board[0].strategy == "s_a"


def test_strategies_ranked_by_score() -> None:
    t = StrategyPerformanceTracker()
    for i in range(10):
        t.record(_win_outcome(i))
    for i in range(10, 15):
        t.record(_loss_outcome(i))
    board = build_leaderboard(t)
    # s_a (wins) should rank above s_b (losses).
    assert board[0].strategy == "s_a"
    assert board[1].strategy == "s_b"
    assert board[0].score > board[1].score


def test_leaderboard_entry_has_metrics() -> None:
    t = StrategyPerformanceTracker()
    t.record(_win_outcome(1))
    board = build_leaderboard(t)
    assert board[0].metrics.total_trades >= 1


def test_ranking_ordering() -> None:
    t = StrategyPerformanceTracker()
    # Strategy X: large wins.
    for i in range(20):
        t.record(TradeOutcome(
            strategy="x", symbol="BTCUSDT", side="long",
            entry_price=100.0, exit_price=110.0, quantity=1.0,
            pnl=10.0, opened_at=float(i), closed_at=float(i),
        ))
    # Strategy Y: small wins.
    for i in range(20, 30):
        t.record(TradeOutcome(
            strategy="y", symbol="BTCUSDT", side="long",
            entry_price=100.0, exit_price=101.0, quantity=1.0,
            pnl=1.0, opened_at=float(i), closed_at=float(i),
        ))
    board = build_leaderboard(t)
    # Both have positive expectancy; X has higher PnL total.
    assert board[0].rank < board[1].rank
    assert board[0].strategy == "x"
