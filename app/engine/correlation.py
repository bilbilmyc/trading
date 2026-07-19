"""Correlation helpers for research views and pre-trade risk controls."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CorrelationMatrix:
    strategies: list[str]
    matrix: list[list[float]]  # matrix[i][j] = correlation between i and j


@dataclass(frozen=True)
class CorrelationSnapshot:
    """Aligned return correlations between one candidate and active positions."""

    symbol: str
    correlations: dict[str, float] = field(default_factory=dict)
    sample_sizes: dict[str, int] = field(default_factory=dict)
    unavailable_symbols: tuple[str, ...] = ()

    def max_positive_pair(self) -> tuple[str, float] | None:
        """Return the most positively correlated eligible position, if any."""
        positive = [item for item in self.correlations.items() if item[1] > 0]
        return max(positive, key=lambda item: item[1]) if positive else None

    def as_dict(self) -> dict[str, object]:
        """Return JSON-friendly correlation evidence for risk status/audit views."""
        return {
            "symbol": self.symbol,
            "correlations": dict(sorted(self.correlations.items())),
            "sample_sizes": dict(sorted(self.sample_sizes.items())),
            "unavailable_symbols": list(sorted(self.unavailable_symbols)),
        }


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


def _timestamp_key(value: object) -> int | None:
    """Normalize adapter candle timestamps to UTC epoch milliseconds."""
    if isinstance(value, datetime):
        return round(value.timestamp() * 1000)
    if isinstance(value, (int, float)) and math.isfinite(value):
        return round(value if abs(value) >= 100_000_000_000 else value * 1000)
    return None


def _close_by_timestamp(candles: Iterable[Mapping[str, Any]]) -> dict[int, float]:
    """Read finite positive closes from a heterogeneous exchange candle shape."""
    closes: dict[int, float] = {}
    for candle in candles:
        timestamp = _timestamp_key(candle.get("open_time", candle.get("timestamp")))
        try:
            close = float(candle.get("close"))
        except (TypeError, ValueError):
            continue
        if timestamp is not None and math.isfinite(close) and close > 0:
            closes[timestamp] = close
    return closes


def aligned_return_correlation(
    left_candles: Iterable[Mapping[str, Any]],
    right_candles: Iterable[Mapping[str, Any]],
    *,
    min_samples: int,
) -> tuple[float, int] | None:
    """Calculate percentage-return correlation using only shared candle times."""
    left = _close_by_timestamp(left_candles)
    right = _close_by_timestamp(right_candles)
    timestamps = sorted(left.keys() & right.keys())
    if len(timestamps) < min_samples + 1:
        return None
    left_returns = [
        left[current] / left[previous] - 1
        for previous, current in zip(timestamps[:-1], timestamps[1:], strict=True)
    ]
    right_returns = [
        right[current] / right[previous] - 1
        for previous, current in zip(timestamps[:-1], timestamps[1:], strict=True)
    ]
    if len(left_returns) < min_samples:
        return None
    return _pearson(left_returns, right_returns), len(left_returns)


def position_correlation_snapshot(
    symbol: str,
    candidate_candles: Iterable[Mapping[str, Any]],
    position_candles: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    min_samples: int,
    unavailable_symbols: Iterable[str] = (),
) -> CorrelationSnapshot:
    """Build candidate-to-position correlations with an explicit sample floor."""
    correlations: dict[str, float] = {}
    sample_sizes: dict[str, int] = {}
    normalized_symbol = symbol.upper()
    for position_symbol, candles in position_candles.items():
        normalized_position = position_symbol.upper()
        if normalized_position == normalized_symbol:
            continue
        result = aligned_return_correlation(
            candidate_candles,
            candles,
            min_samples=min_samples,
        )
        if result is not None:
            correlation, samples = result
            correlations[normalized_position] = correlation
            sample_sizes[normalized_position] = samples
    return CorrelationSnapshot(
        symbol=normalized_symbol,
        correlations=correlations,
        sample_sizes=sample_sizes,
        unavailable_symbols=tuple(item.upper() for item in unavailable_symbols),
    )


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


__all__ = [
    "CorrelationMatrix",
    "CorrelationSnapshot",
    "aligned_return_correlation",
    "position_correlation_snapshot",
    "correlation_matrix",
    "avg_pairwise_correlation",
]
