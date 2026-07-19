from datetime import UTC, datetime, timedelta

from app.engine.correlation import (
    aligned_return_correlation,
    avg_pairwise_correlation,
    correlation_matrix,
    position_correlation_snapshot,
)


def test_single_strategy_perfect_self_correlation() -> None:
    m = correlation_matrix({"a": [100, 101, 102, 103, 104]})
    assert m.matrix[0][0] == 1.0


def test_two_strategies_perfect_positive_correlation() -> None:
    """Two strategies with similar trend → correlation > 0.5."""
    a = [100, 102, 105, 109, 114, 120]
    b = [200, 203, 207, 212, 218, 225]
    m = correlation_matrix({"a": a, "b": b})
    assert m.matrix[0][1] > 0.5
    assert m.matrix[1][0] == m.matrix[0][1]


def test_two_strategies_uncorrelated() -> None:
    """Random walk vs constant → near 0 correlation."""
    import random

    random.seed(42)
    a = [100 + i + random.gauss(0, 1) for i in range(50)]
    b = [100 + random.gauss(0, 0.01) for _ in range(50)]  # noise
    m = correlation_matrix({"a": a, "b": b})
    assert abs(m.matrix[0][1]) < 0.3


def test_perfect_anti_correlation() -> None:
    a = [100, 102, 105, 110, 113, 117]
    b = [200, 198, 195, 190, 187, 183]  # decreasing
    m = correlation_matrix({"a": a, "b": b})
    assert m.matrix[0][1] < -0.99


def test_avg_pairwise_correlation() -> None:
    m = correlation_matrix(
        {
            "a": [100, 102, 105, 109, 114],
            "b": [200, 202, 205, 209, 214],
            "c": [300, 302, 305, 309, 314],
        }
    )
    avg = avg_pairwise_correlation(m)
    # All perfectly correlated, so avg should be ~1.0.
    assert avg > 0.99


def test_matrix_symmetric() -> None:
    m = correlation_matrix(
        {
            "a": [100, 101, 102, 103],
            "b": [200, 199, 198, 197],
            "c": [300, 305, 310, 315],
        }
    )
    n = len(m.matrix)
    for i in range(n):
        for j in range(n):
            assert m.matrix[i][j] == m.matrix[j][i]


def test_short_curves_zero_correlation() -> None:
    m = correlation_matrix({"a": [100], "b": [200]})
    assert m.matrix[0][1] == 0.0


def _candles(closes: list[float]) -> list[dict[str, object]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {"open_time": start + timedelta(hours=index), "close": close}
        for index, close in enumerate(closes)
    ]


def test_aligned_return_correlation_requires_sample_floor_and_uses_common_times() -> None:
    left = _candles([100, 102, 105, 108, 112])
    right = _candles([200, 204, 210, 216, 224])

    result = aligned_return_correlation(left, right, min_samples=4)

    assert result is not None
    correlation, samples = result
    assert samples == 4
    assert correlation > 0.99
    assert aligned_return_correlation(left, right, min_samples=5) is None


def test_position_correlation_snapshot_omits_insufficient_or_same_symbol_data() -> None:
    candidate = _candles([100, 102, 105, 108, 112])
    snapshot = position_correlation_snapshot(
        "ETHUSDT",
        candidate,
        {
            "BTCUSDT": _candles([200, 204, 210, 216, 224]),
            "ETHUSDT": _candles([10, 11, 12, 13, 14]),
            "SOLUSDT": _candles([10, 11]),
        },
        min_samples=4,
        unavailable_symbols=("DOGEUSDT",),
    )

    assert snapshot.max_positive_pair() is not None
    assert snapshot.max_positive_pair()[0] == "BTCUSDT"
    assert snapshot.sample_sizes == {"BTCUSDT": 4}
    assert snapshot.unavailable_symbols == ("DOGEUSDT",)
