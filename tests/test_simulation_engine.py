"""Tests for the shared deterministic event-driven simulation engine."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.engine.simulation import (
    AccountSnapshot,
    EventDrivenSimulationEngine,
    ExecutionModelConfig,
    MarketEvent,
    SignalEvent,
    SimulationConfig,
    SimulationEventType,
    SimulationOrderStatus,
)


def _markets(
    rows: list[tuple[float, float, float, float, float]],
) -> list[MarketEvent]:
    return [
        MarketEvent(
            index=index,
            time=index,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        for index, (open_price, high, low, close, volume) in enumerate(rows)
    ]


def _enter_after_first_close(
    markets: Sequence[MarketEvent],
    index: int,
    account: AccountSnapshot,
) -> SignalEvent | None:
    del account
    if index == 0:
        return SignalEvent(index=index, time=markets[index].time, action="enter")
    return None


def test_signal_executes_on_next_market_open() -> None:
    markets = _markets(
        [
            (100, 100, 100, 100, 100),
            (120, 125, 115, 121, 100),
        ]
    )
    engine = EventDrivenSimulationEngine(
        SimulationConfig(execution=ExecutionModelConfig(fee_rate=0))
    )

    result = engine.run(markets, _enter_after_first_close)

    assert result.trades[0].entry_index == 1
    assert result.trades[0].entry_price == 120
    assert result.trades[0].exit_reason == "end_of_data"
    event_types = [event.event_type for event in result.events]
    signal_index = event_types.index(SimulationEventType.SIGNAL)
    order_index = event_types.index(SimulationEventType.ORDER)
    fill_index = event_types.index(SimulationEventType.FILL)
    assert signal_index < order_index < fill_index


def test_execution_model_applies_adverse_slippage_and_fees() -> None:
    markets = _markets(
        [
            (100, 100, 100, 100, 100),
            (100, 110, 90, 110, 100),
        ]
    )
    engine = EventDrivenSimulationEngine(
        SimulationConfig(
            initial_capital=1_000,
            execution=ExecutionModelConfig(fee_rate=0.001, slippage_rate=0.01),
        )
    )

    result = engine.run(markets, _enter_after_first_close)

    entry_fill, exit_fill = result.fills
    assert entry_fill.price == pytest.approx(101)
    assert exit_fill.price == pytest.approx(108.9)
    assert entry_fill.fee > 0
    assert exit_fill.fee > 0
    assert result.final_equity < 1_000 + entry_fill.filled_quantity * (110 - 100)


def test_volume_participation_produces_partial_fill() -> None:
    markets = _markets(
        [
            (100, 100, 100, 100, 100),
            (100, 100, 100, 100, 2),
        ]
    )
    engine = EventDrivenSimulationEngine(
        SimulationConfig(
            initial_capital=1_000,
            execution=ExecutionModelConfig(
                fee_rate=0,
                max_volume_participation=0.25,
            ),
        )
    )

    result = engine.run(markets, _enter_after_first_close)

    entry_fill = result.fills[0]
    assert entry_fill.requested_quantity == pytest.approx(10)
    assert entry_fill.filled_quantity == pytest.approx(0.5)
    assert entry_fill.remaining_quantity == pytest.approx(9.5)
    assert entry_fill.status == SimulationOrderStatus.PARTIALLY_FILLED
    assert result.trades[0].quantity == pytest.approx(0.5)
    assert result.final_equity == pytest.approx(1_000)


def test_reusing_engine_is_deterministic() -> None:
    markets = _markets(
        [
            (100, 100, 100, 100, 100),
            (105, 110, 100, 108, 100),
        ]
    )
    engine = EventDrivenSimulationEngine(
        SimulationConfig(execution=ExecutionModelConfig(fee_rate=0))
    )

    first = engine.run(markets, _enter_after_first_close)
    second = engine.run(markets, _enter_after_first_close)

    assert first.final_equity == second.final_equity
    assert first.trades == second.trades
    assert first.fills == second.fills
    assert first.events == second.events


def test_engine_rejects_non_contiguous_market_indices() -> None:
    markets = [
        MarketEvent(index=1, time=0, open=100, high=100, low=100, close=100, volume=1)
    ]
    engine = EventDrivenSimulationEngine(SimulationConfig())

    with pytest.raises(ValueError, match="contiguous"):
        engine.run(markets, _enter_after_first_close)

