"""Deterministic market indicators used to ground LLM trading analysis."""

from __future__ import annotations

import math
from typing import Any

from app.engine.rsi import compute_rsi


def valid_klines(klines: list[dict[str, Any]]) -> list[dict[str, float | Any]]:
    """Normalize valid OHLCV rows in chronological order."""
    valid: list[dict[str, float | Any]] = []
    for row in sorted(klines, key=lambda k: str(k.get("open_time", ""))):
        try:
            opened = float(row.get("open", 0))
            high = float(row.get("high", 0))
            low = float(row.get("low", 0))
            close = float(row.get("close", 0))
            volume = float(row.get("volume", 0))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (opened, high, low, close, volume)):
            continue
        if min(opened, high, low, close) <= 0 or high < low:
            continue
        valid.append(
            {
                "open_time": row.get("open_time", ""),
                "open": opened,
                "high": high,
                "low": low,
                "close": close,
                "volume": max(0.0, volume),
            }
        )
    return valid


def true_ranges(ordered: list[dict[str, float | Any]]) -> list[float]:
    """Calculate true range with the prior close, including price gaps."""
    ranges: list[float] = []
    previous_close: float | None = None
    for row in ordered:
        high = float(row["high"])
        low = float(row["low"])
        if previous_close is None:
            ranges.append(high - low)
        else:
            ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = float(row["close"])
    return ranges


def technical_snapshot(klines: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute a compact set of trend, momentum, volatility, and volume indicators."""
    ordered = valid_klines(klines)
    if not ordered:
        return {"count": 0, "data_quality": "unavailable", "trend_bias": "neutral"}

    closes = [float(row["close"]) for row in ordered]
    volumes = [float(row["volume"]) for row in ordered]
    last_close = closes[-1]

    def average(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    def momentum(period: int) -> float | None:
        if len(closes) <= period or closes[-period - 1] <= 0:
            return None
        return (last_close / closes[-period - 1] - 1.0) * 100.0

    sma_5 = average(closes[-5:]) if len(closes) >= 5 else None
    sma_20 = average(closes[-20:]) if len(closes) >= 20 else None
    momentum_5 = momentum(5)
    momentum_20 = momentum(20)
    ranges = true_ranges(ordered)
    atr_14 = average(ranges[-14:]) if len(ranges) >= 14 else average(ranges)
    atr_pct = (atr_14 / last_close * 100.0) if atr_14 and last_close > 0 else None

    recent_volume = average(volumes[-5:]) if len(volumes) >= 5 else average(volumes)
    baseline_slice = volumes[-25:-5] if len(volumes) >= 25 else volumes[:-5]
    baseline_volume = average(baseline_slice)
    volume_ratio = (
        recent_volume / baseline_volume
        if recent_volume is not None and baseline_volume is not None and baseline_volume > 0
        else None
    )

    trend_bias = "neutral"
    if sma_5 is not None and sma_20 is not None and momentum_20 is not None:
        if sma_5 > sma_20 and momentum_20 > 0:
            trend_bias = "bullish"
        elif sma_5 < sma_20 and momentum_20 < 0:
            trend_bias = "bearish"

    rsi_series = compute_rsi(closes, period=14)
    rsi_14 = rsi_series[-1] if len(closes) >= 15 else None
    lookback = ordered[-20:]
    snapshot = {
        "count": len(ordered),
        "data_quality": "sufficient" if len(ordered) >= 20 else "limited",
        "trend_bias": trend_bias,
        "sma_5": sma_5,
        "sma_20": sma_20,
        "rsi_14": rsi_14,
        "momentum_5_pct": momentum_5,
        "momentum_20_pct": momentum_20,
        "atr_14": atr_14,
        "atr_pct": atr_pct,
        "volume_ratio": volume_ratio,
        "support_20": min(float(row["low"]) for row in lookback),
        "resistance_20": max(float(row["high"]) for row in lookback),
    }
    return {
        key: round(value, 4) if isinstance(value, float) else value
        for key, value in snapshot.items()
    }


def kline_summary(klines: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate orientation stats for the compact K-line header."""
    ordered = valid_klines(klines)
    if not ordered:
        return {"count": 0}
    closes = [float(row["close"]) for row in ordered]
    highs = [float(row["high"]) for row in ordered]
    lows = [float(row["low"]) for row in ordered]
    ranges = true_ranges(ordered)
    return {
        "count": len(ordered),
        "first_close": closes[0],
        "last_close": closes[-1],
        "max_high": max(highs),
        "min_low": min(lows),
        "atr": sum(ranges) / len(ranges),
    }


def format_technical_section(snapshot: dict[str, Any]) -> str:
    """Render deterministic indicators so the model can cite verifiable evidence."""
    if not snapshot or snapshot.get("data_quality") == "unavailable":
        return "- 技术指标不可用；不得据此生成高置信度方向建议"

    def value(name: str, suffix: str = "") -> str:
        item = snapshot.get(name)
        return "--" if item is None else f"{item}{suffix}"

    return (
        f"- 数据质量: {snapshot.get('data_quality', 'limited')}，有效 K 线: {snapshot.get('count', 0)}\n"
        f"- 趋势对齐: {snapshot.get('trend_bias', 'neutral')}\n"
        f"- SMA5 / SMA20: {value('sma_5')} / {value('sma_20')}\n"
        f"- RSI14: {value('rsi_14')}\n"
        f"- 5周期 / 20周期动量: {value('momentum_5_pct', '%')} / {value('momentum_20_pct', '%')}\n"
        f"- ATR14 / ATR占价格: {value('atr_14')} / {value('atr_pct', '%')}\n"
        f"- 近期量比: {value('volume_ratio')}\n"
        f"- 20周期支撑 / 阻力: {value('support_20')} / {value('resistance_20')}"
    )


__all__ = [
    "format_technical_section",
    "kline_summary",
    "technical_snapshot",
    "true_ranges",
    "valid_klines",
]
