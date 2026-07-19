from __future__ import annotations

import pytest

from app.engine.in_out_sample import run_in_out_sample_sma_backtest


def _candles(count: int) -> list[dict[str, float | str]]:
    return [
        {
            "open_time": f"2026-01-01T{index:02d}:00:00",
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.0 + index + (0.5 if index % 3 else -0.5),
            "volume": 100.0,
        }
        for index in range(count)
    ]


def test_in_out_sample_uses_contiguous_independent_fixed_parameter_segments() -> None:
    result = run_in_out_sample_sma_backtest(
        _candles(20), in_sample_size=10, short_window=2, long_window=4, fee_rate=0
    )

    assert result.in_sample_size == 10
    assert result.out_sample_size == 10
    assert result.in_sample.initial_capital == 10_000.0
    assert result.out_sample.initial_capital == 10_000.0


@pytest.mark.parametrize("in_sample_size", [4, 16])
def test_in_out_sample_rejects_segments_too_short(in_sample_size: int) -> None:
    with pytest.raises(ValueError):
        run_in_out_sample_sma_backtest(
            _candles(20), in_sample_size=in_sample_size, short_window=2, long_window=4
        )
