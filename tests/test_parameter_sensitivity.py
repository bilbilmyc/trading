from __future__ import annotations

import pytest

from app.engine.parameter_sensitivity import (
    MAX_SENSITIVITY_CANDIDATES,
    run_sma_parameter_sensitivity,
)


def _candles(count: int) -> list[dict[str, float | str]]:
    return [
        {
            "open_time": f"2026-01-01T00:{index:02d}:00",
            "open": 100.0 + index * 0.2,
            "high": 101.0 + index * 0.2,
            "low": 99.0 + index * 0.2,
            "close": 100.0 + index * 0.2 + (0.5 if index % 4 else -0.5),
            "volume": 10.0,
        }
        for index in range(count)
    ]


def test_parameter_sensitivity_returns_stable_local_candidates() -> None:
    trials = run_sma_parameter_sensitivity(
        _candles(30),
        short_window=2,
        long_window=4,
        short_offsets=[1, 0, -1, 0],
        long_offsets=[1, 0, -1],
        fee_rate=0.0,
    )

    assert [
        (trial.short_window, trial.long_window, trial.short_offset, trial.long_offset)
        for trial in trials
    ] == sorted(
        (trial.short_window, trial.long_window, trial.short_offset, trial.long_offset)
        for trial in trials
    )
    assert len(trials) == 8
    baseline = next(trial for trial in trials if trial.short_offset == trial.long_offset == 0)
    assert (baseline.short_window, baseline.long_window) == (2, 4)
    assert set(baseline.as_dict()) == {
        "short_window",
        "long_window",
        "short_offset",
        "long_offset",
        "total_pnl",
        "total_return_pct",
        "max_drawdown",
        "trades",
    }


def test_parameter_sensitivity_rejects_invalid_or_unbounded_candidates() -> None:
    with pytest.raises(ValueError, match="baseline requires"):
        run_sma_parameter_sensitivity(
            _candles(30),
            short_window=3,
            long_window=3,
            short_offsets=[0],
            long_offsets=[0],
        )
    with pytest.raises(ValueError, match="must both include zero"):
        run_sma_parameter_sensitivity(
            _candles(30),
            short_window=2,
            long_window=3,
            short_offsets=[1],
            long_offsets=[0],
        )
    with pytest.raises(ValueError, match=str(MAX_SENSITIVITY_CANDIDATES)):
        run_sma_parameter_sensitivity(
            _candles(80),
            short_window=20,
            long_window=40,
            short_offsets=list(range(-4, 5)),
            long_offsets=list(range(-4, 5)),
        )
