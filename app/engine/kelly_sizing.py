"""Kelly criterion position sizing for binary-outcome bets.

Optimal fraction of bankroll to risk = (bp - q) / b where:
  b = net odds (e.g. 2.0 for 2:1 payoff)
  p = probability of winning
  q = probability of losing (= 1 - p)

For continuous distributions, generalized Kelly = edge / variance.
Half-Kelly is a common conservative adjustment.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KellyResult:
    full_kelly_pct: float       # 0..1
    half_kelly_pct: float       # 0..1
    edge: float                 # expected value per unit risked
    variance: float
    recommended_pct: float      # after half-kelly
    quantity_at_recommended: float
    expected_growth_rate: float  # g(p) = p*ln(1+b*f) + q*ln(1-f)


def kelly_fraction(
    win_prob: float,
    odds: float,
    *,
    fractional: float = 0.5,
) -> KellyResult:
    """Compute Kelly fraction for a binary bet.

    odds: net profit per unit staked on win. E.g. 2.0 for a 2:1 payoff.
    fractional: 0.5 = half-Kelly (more conservative), 1.0 = full Kelly.
    """
    if not 0.0 < win_prob < 1.0:
        raise ValueError("win_prob must be in (0, 1)")
    if odds <= 0:
        raise ValueError("odds must be positive")
    if not 0.0 < fractional <= 1.0:
        raise ValueError("fractional must be in (0, 1]")

    q = 1.0 - win_prob
    b = odds
    f = (b * win_prob - q) / b  # full Kelly
    f = max(0.0, min(f, 1.0))
    f_half = f * fractional

    # Continuous-distribution Kelly (edge / variance) — alternative.
    expected = win_prob * odds - q
    variance = win_prob * (odds - expected) ** 2 + q * (0 - expected) ** 2
    edge_var = expected / variance if variance > 0 else 0.0
    edge_var = max(0.0, min(edge_var, 1.0))

    # Expected log growth rate.
    if f > 0 and f < 1:
        growth = win_prob * math.log(1 + b * f) + q * math.log(1 - f)
    else:
        growth = 0.0

    return KellyResult(
        full_kelly_pct=round(f, 4),
        half_kelly_pct=round(f * fractional, 4),
        edge=round(expected, 4),
        variance=round(variance, 4),
        recommended_pct=round(min(f * fractional, edge_var * fractional), 4),
        quantity_at_recommended=round(f * fractional, 4),
        expected_growth_rate=round(growth, 4),
    )


import math  # noqa: E402


__all__ = ["KellyResult", "kelly_fraction"]