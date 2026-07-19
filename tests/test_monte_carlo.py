from __future__ import annotations

import pytest

from app.engine.monte_carlo import (
    MAX_MONTE_CARLO_SIMULATIONS,
    run_trade_sequence_monte_carlo,
)


def test_monte_carlo_is_seeded_and_measures_trade_order_risk() -> None:
    trade_net_pnls = [100.0, -500.0, 500.0]

    first = run_trade_sequence_monte_carlo(
        trade_net_pnls,
        initial_capital=1_000.0,
        simulations=120,
        seed=7,
        drawdown_threshold_pct=0.3,
    )
    second = run_trade_sequence_monte_carlo(
        trade_net_pnls,
        initial_capital=1_000.0,
        simulations=120,
        seed=7,
        drawdown_threshold_pct=0.3,
    )

    assert first == second
    assert first.as_dict()["sampling"] == "trade_order_permutation_without_replacement"
    assert first.ending_equity_p05 == 1_100.0
    assert first.ending_equity_median == 1_100.0
    assert first.ending_equity_p95 == 1_100.0
    assert 0 < first.drawdown_threshold_breach_probability < 1
    assert first.max_drawdown_p95 > 0


def test_monte_carlo_jitter_expands_ending_equity_distribution() -> None:
    result = run_trade_sequence_monte_carlo(
        [100.0, -50.0, 200.0],
        initial_capital=1_000.0,
        simulations=80,
        seed=11,
        return_jitter_pct=0.25,
    )

    assert result.ending_equity_p05 < result.ending_equity_p95
    assert result.negative_ending_equity_probability == 0


@pytest.mark.parametrize(
    ("trade_net_pnls", "initial_capital", "simulations", "message"),
    [
        ([], 1_000.0, 1, "completed trade"),
        ([1.0], 0.0, 1, "initial_capital"),
        ([1.0], 1_000.0, MAX_MONTE_CARLO_SIMULATIONS + 1, "simulations"),
    ],
)
def test_monte_carlo_rejects_invalid_inputs(
    trade_net_pnls: list[float], initial_capital: float, simulations: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        run_trade_sequence_monte_carlo(
            trade_net_pnls,
            initial_capital=initial_capital,
            simulations=simulations,
            seed=1,
        )
