"""Tests for OrderSync + PositionSync — public modules that orchestrate
reconciliation between local state and exchange state."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.engine.order_sync import OrderSync
from app.engine.position_manager import PositionManager
from app.engine.position_sync import PositionSync
from app.models.order import Order, OrderSide, OrderStatus, OrderType


def _exchange_with_open_orders(orders: list[dict[str, Any]]):
    ex = AsyncMock()
    ex.name = "test_ex"
    ex.get_open_orders = AsyncMock(return_value=orders)
    return ex


def _empty_exchange():
    return _exchange_with_open_orders([])


@pytest.mark.asyncio
async def test_order_sync_empty_returns_zero_changes() -> None:
    sync = OrderSync()
    ex = _empty_exchange()
    n = await sync.sync(ex)
    assert n == 0


@pytest.mark.asyncio
async def test_order_sync_fills_status() -> None:
    sync = OrderSync()
    # Local order in NEW state; exchange says FILLED.
    order = Order(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        order_id="o-1",
    )
    sync.track(order)
    # OrderStatus.PENDING is the default; Pydantic coerces to enum.
    assert order.status == OrderStatus.PENDING

    ex = _exchange_with_open_orders(
        [
            {"order_id": "o-1", "status": "filled"},
        ]
    )
    n = await sync.sync(ex)
    assert n == 1
    assert order.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_order_sync_skips_unknown_exchange_orders() -> None:
    sync = OrderSync()
    # Local order not present on exchange.
    order = Order(
        symbol="BTCUSDT",
        exchange="test_ex",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=0.01,
        order_id="local-only",
    )
    sync.track(order)
    ex = _exchange_with_open_orders([])  # exchange has no orders
    n = await sync.sync(ex)
    # Order should be marked CANCELLED since it's no longer on exchange.
    assert n == 1
    assert order.status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_order_sync_reconciles_unknown_order_by_client_order_id() -> None:
    sync = OrderSync()
    order = Order(
        symbol="BTCUSDT",
        exchange="test_ex",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=0.01,
        client_order_id="client-unknown-1",
        status=OrderStatus.UNKNOWN,
    )
    sync.track(order)
    ex = _exchange_with_open_orders(
        [
            {
                "order_id": "exchange-42",
                "client_order_id": "client-unknown-1",
                "status": "open",
                "symbol": "BTCUSDT",
                "side": "buy",
                "type": "limit",
                "quantity": "0.01",
            }
        ]
    )

    changed = await sync.sync(ex)

    assert changed == 1
    assert order.order_id == "exchange-42"
    assert order.status == OrderStatus.PENDING
    assert sync.tracked_count == 1


@pytest.mark.asyncio
async def test_order_sync_keeps_unknown_order_when_not_in_open_orders() -> None:
    sync = OrderSync()
    order = Order(
        symbol="BTCUSDT",
        exchange="test_ex",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        client_order_id="client-ambiguous-1",
        status=OrderStatus.UNKNOWN,
    )
    sync.track(order)

    changed = await sync.sync(_exchange_with_open_orders([]))

    assert changed == 0
    assert order.status == OrderStatus.UNKNOWN
    assert sync.tracked_count == 1


@pytest.mark.asyncio
async def test_order_sync_does_not_cancel_another_exchange_order() -> None:
    sync = OrderSync()
    other = Order(
        symbol="BTCUSDT",
        exchange="other_ex",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=0.01,
        order_id="other-order",
    )
    sync.track(other)

    changed = await sync.sync(_exchange_with_open_orders([]))

    assert changed == 0
    assert other.status == OrderStatus.PENDING


@pytest.mark.asyncio
async def test_order_sync_handles_exchange_error() -> None:
    sync = OrderSync()
    ex = AsyncMock()
    ex.get_open_orders = AsyncMock(side_effect=RuntimeError("network"))
    n = await sync.sync(ex)
    assert n == 0


@pytest.mark.asyncio
async def test_order_sync_translates_statuses() -> None:
    sync = OrderSync()
    for status_str, expected in [
        ("new", OrderStatus.PENDING),
        ("open", OrderStatus.PENDING),
        ("filled", OrderStatus.FILLED),
        ("canceled", OrderStatus.CANCELLED),
        ("cancelled", OrderStatus.CANCELLED),
    ]:
        out = OrderSync._translate_status(status_str)
        assert out == expected


def test_order_sync_translate_status_unknown() -> None:
    assert OrderSync._translate_status("garbage") is None


def test_order_sync_track_dedupes() -> None:
    sync = OrderSync()
    order = Order(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        order_id="o-1",
    )
    sync.track(order)
    sync.track(order)  # second track
    assert len(sync._local_orders) == 1


def test_order_sync_forget_removes() -> None:
    sync = OrderSync()
    order = Order(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        order_id="o-1",
    )
    sync.track(order)
    sync.forget("o-1")
    assert "o-1" not in sync._local_orders


def test_order_sync_on_sync_no_op() -> None:
    sync = OrderSync()
    sync.on_sync(lambda *args, **kwargs: None)
    assert len(sync._callbacks) == 1


def test_order_sync_tracked_count() -> None:
    sync = OrderSync()
    assert sync.tracked_count == 0
    sync.track(
        Order(
            symbol="BTCUSDT",
            exchange="binance_usdm",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01,
            order_id="o-1",
        )
    )
    assert sync.tracked_count == 1


def test_order_sync_open_orders_property() -> None:
    sync = OrderSync()
    order = Order(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        order_id="o-1",
    )
    sync.track(order)
    assert len(sync.open_orders) == 1


# ── PositionSync ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_position_sync_handles_exchange_error() -> None:
    sync = PositionSync(position_manager=PositionManager())
    ex = AsyncMock()
    ex.get_account_balance = AsyncMock(side_effect=RuntimeError("network"))
    ex.get_positions = AsyncMock(side_effect=RuntimeError("network"))
    n = await sync.sync(ex, "test_ex")
    assert n == 0


@pytest.mark.asyncio
async def test_position_sync_updates_balances() -> None:
    pm = PositionManager()
    sync = PositionSync(position_manager=pm)
    ex = AsyncMock()
    ex.name = "test_ex"
    ex.get_account_balance = AsyncMock(return_value={"USDT": 5000.0})
    ex.get_positions = AsyncMock(return_value=[])

    n = await sync.sync(ex, "test_ex")
    assert n >= 1  # at least one balance updated

    balance = await pm.get_balance("test_ex", "USDT")
    assert balance is not None
    assert balance.total == 5000.0


@pytest.mark.asyncio
async def test_position_sync_with_no_exchange_no_op() -> None:
    sync = PositionSync(position_manager=PositionManager())
    n = await sync.sync(None, "x")  # None exchange
    assert n == 0


def test_position_sync_interval_property() -> None:
    sync = PositionSync(position_manager=PositionManager(), interval_seconds=20)
    assert sync.interval_seconds == 20


def test_position_sync_initialized() -> None:
    sync = PositionSync(position_manager=PositionManager())
    assert sync.position_manager is not None
    assert sync.interval_seconds == 15  # default
