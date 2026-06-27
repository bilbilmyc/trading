"""Tests for PositionManager — in-memory position tracking."""

from __future__ import annotations

import pytest

from app.engine.position_manager import PositionManager
from app.models.position import Position


@pytest.mark.asyncio
async def test_get_position_returns_none_initially() -> None:
    pm = PositionManager()
    pos = await pm.get_position("binance_usdm", "BTCUSDT")
    assert pos is None


@pytest.mark.asyncio
async def test_update_position_long() -> None:
    pm = PositionManager()
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 50_000.0, "buy")
    pos = await pm.get_position("binance_usdm", "BTCUSDT")
    assert pos is not None
    assert pos.quantity == 0.1
    assert pos.avg_entry_price == 50_000.0


@pytest.mark.asyncio
async def test_update_position_increases_quantity_uses_avg() -> None:
    pm = PositionManager()
    # Buy 0.1 @ 50k, then 0.1 @ 60k → avg should be 55k, qty 0.2.
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 50_000.0, "buy")
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 60_000.0, "buy")
    pos = await pm.get_position("binance_usdm", "BTCUSDT")
    assert pos.quantity == 0.2
    assert pos.avg_entry_price == 55_000.0


@pytest.mark.asyncio
async def test_update_position_sell_reduces_quantity() -> None:
    pm = PositionManager()
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 50_000.0, "buy")
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 55_000.0, "sell")
    pos = await pm.get_position("binance_usdm", "BTCUSDT")
    assert pos.quantity == 0.0


@pytest.mark.asyncio
async def test_update_position_reverses_long_to_short() -> None:
    pm = PositionManager()
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 50_000.0, "buy")
    # Sell more than held → short position at the new price.
    await pm.update_position("binance_usdm", "BTCUSDT", 0.2, 60_000.0, "sell")
    pos = await pm.get_position("binance_usdm", "BTCUSDT")
    assert pos.quantity == -0.1
    assert pos.avg_entry_price == 60_000.0


@pytest.mark.asyncio
async def test_update_price_marks_to_market() -> None:
    pm = PositionManager()
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 50_000.0, "buy")
    await pm.update_price("binance_usdm", "BTCUSDT", 55_000.0)
    pos = await pm.get_position("binance_usdm", "BTCUSDT")
    assert pos.current_price == 55_000.0


@pytest.mark.asyncio
async def test_get_all_positions_returns_dict() -> None:
    pm = PositionManager()
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 50_000.0, "buy")
    positions = await pm.get_all_positions()
    assert "binance_usdm:BTCUSDT" in positions


@pytest.mark.asyncio
async def test_get_balance_returns_none_initially() -> None:
    pm = PositionManager()
    bal = await pm.get_balance("binance_usdm", "USDT")
    assert bal is None


@pytest.mark.asyncio
async def test_update_balance_persists() -> None:
    pm = PositionManager()
    await pm.update_balance("binance_usdm", "USDT", 1000.0, 800.0)
    bal = await pm.get_balance("binance_usdm", "USDT")
    assert bal is not None
    assert bal.total == 1000.0
    assert bal.available == 800.0


@pytest.mark.asyncio
async def test_get_position_summary_shape() -> None:
    pm = PositionManager()
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 50_000.0, "buy")
    await pm.update_price("binance_usdm", "BTCUSDT", 55_000.0)
    summary = await pm.get_position_summary()
    assert "positions" in summary or "total_unrealized_pnl" in summary


def test_position_manager_initial_state() -> None:
    pm = PositionManager()
    assert pm._positions == {}
    assert pm._balances == {}


@pytest.mark.asyncio
async def test_position_manager_update_position_with_price_none() -> None:
    """update_position with price=None should not crash."""
    pm = PositionManager()
    await pm.update_position("binance_usdm", "BTCUSDT", 0.1, 0.0, "buy")
    pos = await pm.get_position("binance_usdm", "BTCUSDT")
    assert pos is not None
    assert pos.avg_entry_price == 0.0