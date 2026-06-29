"""Strategy correlation matrix — pairwise correlation of strategy returns.

Used to spot strategies that move together (low diversification) vs
those that complement each other (high diversification).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class CorrelationMatrix:
    strategies: list[str]
    matrix: list[list[float]]  # matrix[i][j] = correlation between i and j


def _returns(equity_curve: Sequence[float]) -> list[float]:
    if len(equity_curve) < 2:
        return []
    return [equity_curve[i] - equity_curve[i - 1] for i in range(1, len(equity_curve))]


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    xs = list(xs[:n])
    ys = list(ys[:n])
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)


def correlation_matrix(
    equity_curves: dict[str, Sequence[float]],
) -> CorrelationMatrix:
    """Build pairwise correlation matrix from per-strategy equity curves.

    Returns a symmetric matrix with 1.0 on the diagonal.
    """
    strategies = list(equity_curves.keys())
    returns = {name: _returns(curve) for name, curve in equity_curves.items()}
    matrix: list[list[float]] = []
    for i, name_i in enumerate(strategies):
        row: list[float] = []
        for j, name_j in enumerate(strategies):
            if i == j:
                row.append(1.0)
            else:
                row.append(_pearson(returns[name_i], returns[name_j]))
        matrix.append(row)
    return CorrelationMatrix(strategies=strategies, matrix=matrix)


def avg_pairwise_correlation(matrix: CorrelationMatrix) -> float:
    """Mean off-diagonal correlation — measures portfolio diversification."""
    if not matrix.matrix or len(matrix.matrix) < 2:
        return 0.0
    n = len(matrix.matrix)
    total = 0.0
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += matrix.matrix[i][j]
            count += 1
    return total / count if count else 0.0


__all__ = ["CorrelationMatrix", "correlation_matrix", "avg_pairwise_correlation"]
