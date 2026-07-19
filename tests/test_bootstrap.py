from __future__ import annotations

import pytest

from app.engine.bootstrap import MAX_BOOTSTRAP_SIMULATIONS, run_trade_pnl_bootstrap


def test_bootstrap_is_seeded_and_resamples_trade_pnls_with_replacement() -> None:
    trade_net_pnls = [100.0, -500.0, 500.0]

    first = run_trade_pnl_bootstrap(
        trade_net_pnls,
        initial_capital=1_000.0,
        simulations=120,
        seed=7,
        drawdown_threshold_pct=0.3,
    )
    second = run_trade_pnl_bootstrap(
        trade_net_pnls,
        initial_capital=1_000.0,
        simulations=120,
        seed=7,
        drawdown_threshold_pct=0.3,
    )

    assert first == second
    assert first.as_dict()["sampling"] == "trade_pnl_bootstrap_with_replacement"
    assert first.ending_equity_p05 == 100.0
    assert first.ending_equity_median == 1_100.0
    assert first.ending_equity_p95 == 2_120.0
    assert first.ending_equity_p05 < first.ending_equity_p95
    assert first.negative_ending_equity_probability > 0


@pytest.mark.parametrize(
    ("trade_net_pnls", "initial_capital", "simulations", "message"),
    [
        ([], 1_000.0, 1, "completed trade"),
        ([1.0], 0.0, 1, "initial_capital"),
        ([1.0], 1_000.0, MAX_BOOTSTRAP_SIMULATIONS + 1, "simulations"),
    ],
)
def test_bootstrap_rejects_invalid_inputs(
    trade_net_pnls: list[float], initial_capital: float, simulations: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        run_trade_pnl_bootstrap(
            trade_net_pnls,
            initial_capital=initial_capital,
            simulations=simulations,
            seed=1,
        )
