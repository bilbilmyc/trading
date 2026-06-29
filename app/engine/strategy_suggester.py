"""AI strategy suggester — proposes SMA / RSI parameters from klines.

Pure-function: given recent klines, compute stats (volatility, trend,
mean-reversion signal) and emit a suggested strategy + parameters.
The result feeds into a StrategyInfo the user can accept and register.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StrategySuggestion:
    kind: str                # "sma_crossover" | "rsi_mean_reversion"
    params: dict[str, Any]
    rationale: str


def _stddev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5


def _returns(closes: list[float]) -> list[float]:
    return [closes[i] - closes[i - 1] for i in range(1, len(closes))]


def suggest_strategy(
    candles: list[dict[str, Any]],
    *,
    prefer: str | None = None,    # "sma" | "rsi" | None (auto)
) -> StrategySuggestion:
    """Pick a strategy + parameters based on recent kline behavior."""
    closes = [float(c.get("close", 0)) for c in candles]
    n = len(closes)
    if n < 30:
        return StrategySuggestion(
            kind="sma_crossover",
            params={"short_window": 5, "long_window": 20},
            rationale="数据不足 30 根，使用默认 SMA(5,20)。",
        )

    last = closes[-1]
    first = closes[0]
    trend_strength = abs(last - first) / first

    if prefer == "rsi" or (prefer is None and trend_strength < 0.05):
        return StrategySuggestion(
            kind="rsi_mean_reversion",
            params={"period": 14, "oversold": 30.0, "overbought": 70.0},
            rationale=(
                f"近 {n} 根趋势弱（{trend_strength * 100:.1f}%），"
                "适合 RSI 均值回归策略。"
            ),
        )

    if trend_strength > 0.15:
        short_w = 10
        long_w = 40
        rationale = (
            f"近 {n} 根强趋势（{trend_strength * 100:.1f}%），"
            "建议较宽 SMA 通道 (10/40) 以减少假突破。"
        )
    else:
        short_w = 5
        long_w = 20
        rationale = (
            f"近 {n} 根趋势温和（{trend_strength * 100:.1f}%），"
            "默认 SMA(5,20) 适合当前节奏。"
        )

    return StrategySuggestion(
        kind="sma_crossover",
        params={"short_window": short_w, "long_window": long_w},
        rationale=rationale,
    )


__all__ = ["StrategySuggestion", "suggest_strategy"]
