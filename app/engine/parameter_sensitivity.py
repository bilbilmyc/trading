"""Bounded local SMA parameter-sensitivity diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engine.backtest import BacktestResult, run_sma_backtest

MAX_SENSITIVITY_CANDIDATES = 64


@dataclass(frozen=True)
class SensitivityTrial:
    short_window: int
    long_window: int
    short_offset: int
    long_offset: int
    result: BacktestResult

    def as_dict(self) -> dict[str, float | int]:
        return {
            "short_window": self.short_window,
            "long_window": self.long_window,
            "short_offset": self.short_offset,
            "long_offset": self.long_offset,
            "total_pnl": self.result.total_pnl,
            "total_return_pct": self.result.total_return_pct,
            "max_drawdown": self.result.max_drawdown,
            "trades": self.result.trades,
        }


def run_sma_parameter_sensitivity(
    candles: list[dict[str, Any]],
    *,
    short_window: int,
    long_window: int,
    short_offsets: list[int],
    long_offsets: list[int],
    **execution: Any,
) -> list[SensitivityTrial]:
    """Evaluate bounded local fixed-parameter variations around one SMA baseline."""
    if short_window <= 0 or long_window <= 0 or short_window >= long_window:
        raise ValueError("baseline requires positive short_window < long_window")
    if 0 not in short_offsets or 0 not in long_offsets:
        raise ValueError("short_offsets and long_offsets must both include zero")
    candidates = sorted(
        {
            (short_window + so, long_window + lo, so, lo)
            for so in short_offsets
            for lo in long_offsets
            if short_window + so > 0
            and long_window + lo > 0
            and short_window + so < long_window + lo
        }
    )
    if not candidates:
        raise ValueError("offsets must produce at least one valid short_window < long_window pair")
    if len(candidates) > MAX_SENSITIVITY_CANDIDATES:
        raise ValueError(
            f"sensitivity request would create {len(candidates)} candidates; maximum is {MAX_SENSITIVITY_CANDIDATES}"
        )
    return [
        SensitivityTrial(
            short,
            long,
            so,
            lo,
            run_sma_backtest(candles, short_window=short, long_window=long, **execution),
        )
        for short, long, so, lo in candidates
    ]


__all__ = ["MAX_SENSITIVITY_CANDIDATES", "SensitivityTrial", "run_sma_parameter_sensitivity"]
