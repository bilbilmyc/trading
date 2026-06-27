from datetime import datetime
from app.engine.walk_forward import walk_forward_sma, WalkForwardResult


def _candles(n: int, start: float = 100.0) -> list:
    return [
        {
            "open_time": datetime(2026, 1, 1) + __import__("datetime").timedelta(days=i),
            "open": start + i * 0.5,
            "high": start + i * 0.5 + 1,
            "low": start + i * 0.5 - 1,
            "close": start + i * 0.5,
            "volume": 1.0,
        }
        for i in range(n)
    ]


def test_too_few_candles_returns_empty() -> None:
    r = walk_forward_sma(_candles(10))
    assert isinstance(r, WalkForwardResult)
    assert r.windows == []


def test_basic_walk_forward() -> None:
    candles = _candles(200)
    r = walk_forward_sma(candles, n_windows=4, train_pct=0.7)
    # Walk forward runs and produces windows; aggregate PnL is finite.
    assert len(r.windows) >= 1
    assert isinstance(r.aggregate_oos_pnl, float)


def test_walk_forward_window_count() -> None:
    candles = _candles(200)
    r = walk_forward_sma(candles, n_windows=4, train_pct=0.7)
    # 4 windows expected (one per chunk).
    assert len(r.windows) == 4


def test_walk_forward_window_in_out_partition() -> None:
    candles = _candles(120)
    r = walk_forward_sma(candles, n_windows=2, train_pct=0.5)
    for w in r.windows:
        assert w.train_end == w.test_start  # contiguous split
        assert w.train_end - w.train_start == w.test_end - w.test_start  # 50/50


def test_walk_forward_window_records_best_params() -> None:
    candles = _candles(120)
    r = walk_forward_sma(candles, n_windows=2, train_pct=0.7)
    for w in r.windows:
        assert "short_window" in w.best_params
        assert "long_window" in w.best_params
        assert w.best_params["short_window"] < w.best_params["long_window"]


def test_walk_forward_records_in_out_metrics() -> None:
    candles = _candles(120)
    r = walk_forward_sma(candles, n_windows=2)
    for w in r.windows:
        assert "total_pnl" in w.in_sample_metrics
        assert "total_pnl" in w.out_of_sample_metrics
        assert "trades" in w.in_sample_metrics


def test_walk_forward_result_sharpe_calculation() -> None:
    candles = _candles(200)
    r = walk_forward_sma(candles, n_windows=4, train_pct=0.7)
    # Sharpe is computed from OOS returns; could be any real number.
    assert isinstance(r.aggregate_oos_sharpe, float)


def test_walk_forward_win_rate_in_range() -> None:
    candles = _candles(200)
    r = walk_forward_sma(candles, n_windows=4, train_pct=0.7)
    if r.windows:
        assert 0.0 <= r.aggregate_oos_win_rate <= 1.0


def test_walk_forward_max_dd_in_range() -> None:
    candles = _candles(200)
    r = walk_forward_sma(candles, n_windows=4, train_pct=0.7)
    assert 0.0 <= r.aggregate_max_dd <= 1.0


def test_walk_forward_handles_choppy_market() -> None:
    """Choppy market: returns may be near zero, no exception."""
    import random
    random.seed(0)
    candles = []
    price = 100.0
    for _ in range(200):
        price += random.gauss(0, 1)
        candles.append({
            "open_time": datetime(2026, 1, 1),
            "open": price, "high": price + 0.5, "low": price - 0.5,
            "close": price, "volume": 1.0,
        })
    r = walk_forward_sma(candles, n_windows=4)
    assert isinstance(r, WalkForwardResult)
