"""Execution lifecycle coverage for the phase-two matching model."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.engine.simulation import (
    AccountSnapshot,
    DeterministicBarBroker,
    EventDrivenSimulationEngine,
    ExecutionModelConfig,
    MarketEvent,
    OrderIntent,
    SignalEvent,
    SimulationConfig,
    SimulationOrderStatus,
    SimulationOrderType,
    SimulationSide,
    SimulationTimeInForce,
)
from app.engine.simulation.models import RiskModelConfig


def _market(
    index: int,
    open_price: float = 100.0,
    high: float = 100.0,
    low: float = 100.0,
    close: float = 100.0,
    **kwargs: float | str | None,
) -> MarketEvent:
    return MarketEvent(
        index=index,
        time=index,
        open=open_price,
        high=high,
        low=low,
        close=close,
        **kwargs,
    )


def test_gtc_limit_order_stays_active_after_partial_fill() -> None:
    markets = [
        _market(0),
        _market(1, volume=100),
        _market(2, low=99, close=99, ask=99, ask_size=2, volume=100),
        _market(3, low=99, close=99, ask=99, ask_size=20, volume=100),
    ]

    def signals(
        rows: Sequence[MarketEvent], index: int, account: AccountSnapshot
    ) -> SignalEvent | None:
        del rows, account
        if index == 0:
            return SignalEvent(
                index=0,
                time=0,
                action="enter",
                order_type=SimulationOrderType.LIMIT,
                limit_price=99,
                time_in_force=SimulationTimeInForce.GTC,
            )
        return None

    result = EventDrivenSimulationEngine(
        SimulationConfig(initial_capital=1_000, execution=ExecutionModelConfig(fee_rate=0))
    ).run(markets, signals)

    statuses = [fill.status for fill in result.fills]
    assert SimulationOrderStatus.PENDING in statuses
    assert SimulationOrderStatus.PARTIALLY_FILLED in statuses
    assert SimulationOrderStatus.FILLED in statuses
    entry_fills = [fill for fill in result.fills if fill.side == SimulationSide.BUY]
    assert sum(fill.filled_quantity for fill in entry_fills) == pytest.approx(1_000 / 99)


def test_post_only_fok_expiry_and_cancel_have_terminal_exchange_statuses() -> None:
    broker = DeterministicBarBroker(ExecutionModelConfig(fee_rate=0))
    post_only = OrderIntent(
        order_id="post",
        created_index=0,
        execute_index=0,
        side=SimulationSide.BUY,
        reason="test",
        quantity=1,
        order_type=SimulationOrderType.LIMIT,
        limit_price=100,
        post_only=True,
    )
    post_result = broker.execute(post_only, _market(0, ask=100), cash=1_000, position_quantity=0)
    assert post_result.fill.status == SimulationOrderStatus.REJECTED
    assert post_result.fill.reason == "post_only_would_take"

    ioc_limit = OrderIntent(
        order_id="ioc-limit",
        created_index=0,
        execute_index=0,
        side=SimulationSide.BUY,
        reason="test",
        quantity=1,
        order_type=SimulationOrderType.LIMIT,
        limit_price=90,
    )
    ioc_result = broker.execute(ioc_limit, _market(0), cash=1_000, position_quantity=0)
    assert ioc_result.fill.status == SimulationOrderStatus.REJECTED
    assert ioc_result.fill.reason == "ioc_not_marketable"

    fok = OrderIntent(
        order_id="fok",
        created_index=0,
        execute_index=0,
        side=SimulationSide.BUY,
        reason="test",
        quantity=2,
        order_type=SimulationOrderType.MARKET,
        time_in_force=SimulationTimeInForce.FOK,
    )
    fok_result = broker.execute(fok, _market(0, ask_size=1), cash=1_000, position_quantity=0)
    assert fok_result.fill.status == SimulationOrderStatus.REJECTED
    assert fok_result.fill.reason == "fok_unfilled"

    markets = [_market(0), _market(1), _market(2)]

    def expiry_and_cancel(
        rows: Sequence[MarketEvent], index: int, account: AccountSnapshot
    ) -> SignalEvent | None:
        del rows, account
        if index == 0:
            return SignalEvent(
                index=0,
                time=0,
                action="enter",
                order_type=SimulationOrderType.LIMIT,
                limit_price=90,
                time_in_force=SimulationTimeInForce.GTC,
                expires_index=1,
            )
        if index == 1:
            return SignalEvent(index=1, time=1, action="cancel", cancel_order_id="sim-1")
        return None

    result = EventDrivenSimulationEngine(
        SimulationConfig(execution=ExecutionModelConfig(fee_rate=0))
    ).run(markets, expiry_and_cancel)
    assert result.fills[-1].status == SimulationOrderStatus.CANCELLED

    def expiry_only(
        rows: Sequence[MarketEvent], index: int, account: AccountSnapshot
    ) -> SignalEvent | None:
        del rows, account
        if index == 0:
            return SignalEvent(
                index=0,
                time=0,
                action="enter",
                order_type=SimulationOrderType.LIMIT,
                limit_price=90,
                time_in_force=SimulationTimeInForce.GTC,
                expires_index=1,
            )
        return None

    expiry_result = EventDrivenSimulationEngine(
        SimulationConfig(execution=ExecutionModelConfig(fee_rate=0))
    ).run(markets, expiry_only)
    assert expiry_result.fills[-1].status == SimulationOrderStatus.EXPIRED


def test_latency_regime_slippage_depth_queue_and_conditional_orders() -> None:
    market = _market(
        0,
        open_price=100,
        high=106,
        low=94,
        close=100,
        bid=99,
        ask=101,
        bid_size=4,
        ask_size=4,
        market_regime="volatile",
    )
    broker = DeterministicBarBroker(
        ExecutionModelConfig(
            fee_rate=0,
            slippage_rate=0.01,
            volatile_slippage_multiplier=2,
            queue_position_fraction=0.5,
        )
    )
    market_order = OrderIntent(
        order_id="market",
        created_index=0,
        execute_index=0,
        side=SimulationSide.BUY,
        reason="test",
        quantity=10,
    )
    market_result = broker.execute(market_order, market, cash=10_000, position_quantity=0)
    assert market_result.fill.price == pytest.approx(103.02)
    assert market_result.fill.filled_quantity == pytest.approx(4)

    queued_limit = OrderIntent(
        order_id="queue",
        created_index=0,
        execute_index=0,
        side=SimulationSide.BUY,
        reason="test",
        quantity=10,
        order_type=SimulationOrderType.LIMIT,
        limit_price=95,
    )
    queue_result = broker.execute(queued_limit, market, cash=10_000, position_quantity=0)
    assert queue_result.fill.filled_quantity == pytest.approx(2)
    assert queue_result.fill.price == pytest.approx(95)

    stop = OrderIntent(
        order_id="stop",
        created_index=0,
        execute_index=0,
        side=SimulationSide.BUY,
        reason="stop",
        quantity=1,
        order_type=SimulationOrderType.STOP_MARKET,
        stop_price=105,
    )
    assert broker.execute(stop, market, cash=10_000, position_quantity=0).fill.status == (
        SimulationOrderStatus.FILLED
    )
    take_profit = OrderIntent(
        order_id="take-profit",
        created_index=0,
        execute_index=0,
        side=SimulationSide.SELL,
        reason="take_profit",
        quantity=1,
        order_type=SimulationOrderType.TAKE_PROFIT_MARKET,
        stop_price=105,
    )
    assert broker.execute(take_profit, market, cash=0, position_quantity=1).fill.status == (
        SimulationOrderStatus.FILLED
    )

    latency_markets = [_market(0), _market(1), _market(2)]

    def enter_once(
        rows: Sequence[MarketEvent], index: int, account: AccountSnapshot
    ) -> SignalEvent | None:
        del rows, account
        return SignalEvent(index=index, time=index, action="enter") if index == 0 else None

    latency_result = EventDrivenSimulationEngine(
        SimulationConfig(execution=ExecutionModelConfig(fee_rate=0, additional_latency_bars=1))
    ).run(latency_markets, enter_once)
    assert latency_result.trades[0].entry_index == 2


def test_trailing_stop_closes_after_price_ratchets_higher() -> None:
    markets = [
        _market(0),
        _market(1, open_price=115, high=120, low=115, close=115),
        _market(2, open_price=110, high=111, low=100, close=105),
    ]

    def enter_once(
        rows: Sequence[MarketEvent], index: int, account: AccountSnapshot
    ) -> SignalEvent | None:
        del rows, account
        return SignalEvent(index=index, time=index, action="enter") if index == 0 else None

    result = EventDrivenSimulationEngine(
        SimulationConfig(
            execution=ExecutionModelConfig(fee_rate=0),
            risk=RiskModelConfig(trailing_stop_pct=0.05),
        )
    ).run(markets, enter_once)

    assert result.trades[0].exit_reason == "trailing_stop"
    assert result.trades[0].exit_price == pytest.approx(110)
