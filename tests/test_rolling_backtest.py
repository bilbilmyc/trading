from __future__ import annotations

import pytest

from app.engine.rolling_backtest import (
    MAX_ROLLING_BACKTEST_WINDOWS,
    run_rolling_sma_backtest,
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


def test_rolling_backtest_uses_complete_fixed_parameter_windows() -> None:
    result = run_rolling_sma_backtest(
        _candles(20),
        window_size=8,
        step_size=4,
        short_window=2,
        long_window=4,
        fee_rate=0.0,
    )

    assert [(window.start_index, window.end_index) for window in result.windows] == [
        (0, 7),
        (4, 11),
        (8, 15),
        (12, 19),
    ]
    payload = result.as_dict()
    assert payload["rolling"] == {
        "window_size": 8,
        "step_size": 4,
        "window_count": 4,
        "parameter_mode": "fixed",
        "capital_model": "independent_per_window",
        "max_window_count": MAX_ROLLING_BACKTEST_WINDOWS,
    }
    assert len(payload["windows"]) == 4
    assert all(window["result"]["initial_capital"] == 10_000.0 for window in payload["windows"])
    assert (
        payload["summary"]["worst_window_return_pct"]
        <= payload["summary"]["best_window_return_pct"]
    )


def test_rolling_backtest_rejects_incomplete_or_unbounded_window_requests() -> None:
    with pytest.raises(ValueError, match="not enough candles"):
        run_rolling_sma_backtest(_candles(7), window_size=8)
    with pytest.raises(ValueError, match="step_size must be positive"):
        run_rolling_sma_backtest(_candles(8), window_size=8, step_size=0)
    with pytest.raises(ValueError, match="maximum"):
        run_rolling_sma_backtest(
            _candles(MAX_ROLLING_BACKTEST_WINDOWS + 3),
            window_size=3,
            step_size=1,
        )
