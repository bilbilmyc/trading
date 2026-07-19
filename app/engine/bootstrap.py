"""Deterministic Bootstrap diagnostics for completed-trade P&L samples."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from random import Random

MAX_BOOTSTRAP_SIMULATIONS = 1_000


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _max_drawdown(equity: Sequence[float]) -> float:
    peak = equity[0]
    drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            drawdown = max(drawdown, (peak - value) / peak)
    return drawdown


@dataclass(frozen=True)
class BootstrapResult:
    simulations: int
    seed: int
    drawdown_threshold_pct: float
    ending_equity_p05: float
    ending_equity_median: float
    ending_equity_p95: float
    max_drawdown_p95: float
    drawdown_threshold_breach_probability: float
    negative_ending_equity_probability: float

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "simulations": self.simulations,
            "seed": self.seed,
            "sampling": "trade_pnl_bootstrap_with_replacement",
            "drawdown_threshold_pct": self.drawdown_threshold_pct,
            "ending_equity_p05": self.ending_equity_p05,
            "ending_equity_median": self.ending_equity_median,
            "ending_equity_p95": self.ending_equity_p95,
            "max_drawdown_p95": self.max_drawdown_p95,
            "drawdown_threshold_breach_probability": self.drawdown_threshold_breach_probability,
            "negative_ending_equity_probability": self.negative_ending_equity_probability,
        }


def run_trade_pnl_bootstrap(
    trade_net_pnls: Sequence[float],
    *,
    initial_capital: float,
    simulations: int,
    seed: int,
    drawdown_threshold_pct: float = 0.3,
) -> BootstrapResult:
    """Resample completed trade P&Ls with replacement and measure path risk."""
    pnls = [float(value) for value in trade_net_pnls]
    if not pnls:
        raise ValueError("at least one completed trade is required")
    if not isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    if not 1 <= simulations <= MAX_BOOTSTRAP_SIMULATIONS:
        raise ValueError(f"simulations must be between 1 and {MAX_BOOTSTRAP_SIMULATIONS}")
    if not 0 < drawdown_threshold_pct < 1:
        raise ValueError("drawdown_threshold_pct must be between 0 and 1")
    if any(not isfinite(value) for value in pnls):
        raise ValueError("trade_net_pnls must contain finite values")

    rng = Random(seed)
    endings: list[float] = []
    drawdowns: list[float] = []
    threshold_breaches = 0
    negative_endings = 0
    threshold = initial_capital * (1 - drawdown_threshold_pct)
    for _ in range(simulations):
        equity = initial_capital
        curve = [equity]
        for pnl in rng.choices(pnls, k=len(pnls)):
            equity += pnl
            curve.append(equity)
        endings.append(equity)
        drawdowns.append(_max_drawdown(curve))
        threshold_breaches += int(min(curve) <= threshold)
        negative_endings += int(equity <= 0)

    return BootstrapResult(
        simulations=simulations,
        seed=seed,
        drawdown_threshold_pct=drawdown_threshold_pct,
        ending_equity_p05=round(_percentile(endings, 0.05), 4),
        ending_equity_median=round(_percentile(endings, 0.5), 4),
        ending_equity_p95=round(_percentile(endings, 0.95), 4),
        max_drawdown_p95=round(_percentile(drawdowns, 0.95), 4),
        drawdown_threshold_breach_probability=round(threshold_breaches / simulations, 4),
        negative_ending_equity_probability=round(negative_endings / simulations, 4),
    )


__all__ = ["MAX_BOOTSTRAP_SIMULATIONS", "BootstrapResult", "run_trade_pnl_bootstrap"]
