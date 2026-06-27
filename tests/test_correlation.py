from app.engine.correlation import (
    avg_pairwise_correlation, correlation_matrix,
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
    m = correlation_matrix({
        "a": [100, 102, 105, 109, 114],
        "b": [200, 202, 205, 209, 214],
        "c": [300, 302, 305, 309, 314],
    })
    avg = avg_pairwise_correlation(m)
    # All perfectly correlated, so avg should be ~1.0.
    assert avg > 0.99


def test_matrix_symmetric() -> None:
    m = correlation_matrix({
        "a": [100, 101, 102, 103],
        "b": [200, 199, 198, 197],
        "c": [300, 305, 310, 315],
    })
    n = len(m.matrix)
    for i in range(n):
        for j in range(n):
            assert m.matrix[i][j] == m.matrix[j][i]


def test_short_curves_zero_correlation() -> None:
    m = correlation_matrix({"a": [100], "b": [200]})
    assert m.matrix[0][1] == 0.0
