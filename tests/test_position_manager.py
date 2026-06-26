"""Tests for position management — mark-to-market + close."""

from __future__ import annotations

import pytest

from app.engine.position_mgmt import close_position, mark_to_market


def test_long_position_in_profit() -> None:
    snap = mark_to_market(
        symbol="BTCUSDT",
        side="long",
        quantity=0.1,
        avg_entry_price=100_000.0,
        mark_price=105_000.0,
    )
    assert snap.unrealized_pnl == 500.0
    assert abs(snap.unrealized_pnl_pct - 0.05) < 1e-6


def test_long_position_in_loss() -> None:
    snap = mark_to_market(
        symbol="BTCUSDT",
        side="long",
        quantity=0.1,
        avg_entry_price=100_000.0,
        mark_price=95_000.0,
    )
    assert snap.unrealized_pnl == -500.0
    assert snap.unrealized_pnl_pct < 0


def test_short_position_in_profit() -> None:
    snap = mark_to_market(
        symbol="BTCUSDT",
        side="short",
        quantity=0.1,
        avg_entry_price=100_000.0,
        mark_price=95_000.0,
    )
    assert snap.unrealized_pnl == 500.0


def test_short_position_in_loss() -> None:
    snap = mark_to_market(
        symbol="BTCUSDT",
        side="short",
        quantity=0.1,
        avg_entry_price=100_000.0,
        mark_price=105_000.0,
    )
    assert snap.unrealized_pnl == -500.0


def test_flat_position_returns_zero_pnl() -> None:
    snap = mark_to_market(
        symbol="BTCUSDT",
        side="long",
        quantity=0.0,
        avg_entry_price=0.0,
        mark_price=100.0,
    )
    assert snap.unrealized_pnl == 0.0


def test_close_full_long_position_realizes_pnl() -> None:
    result = close_position(
        side="long",
        quantity=0.1,
        avg_entry_price=100_000.0,
        exit_price=105_000.0,
    )
    assert result.realized_pnl == 500.0
    assert result.remaining_quantity == 0.0


def test_close_partial_long_position() -> None:
    result = close_position(
        side="long",
        quantity=0.2,
        avg_entry_price=100_000.0,
        exit_price=105_000.0,
        close_quantity=0.05,
    )
    assert result.realized_pnl == 250.0
    assert result.remaining_quantity == 0.15


def test_close_short_position_realizes_pnl() -> None:
    result = close_position(
        side="short",
        quantity=0.1,
        avg_entry_price=100_000.0,
        exit_price=95_000.0,
    )
    assert result.realized_pnl == 500.0


def test_close_with_zero_quantity_rejected() -> None:
    with pytest.raises(ValueError):
        close_position(side="long", quantity=0, avg_entry_price=100, exit_price=110)


def test_close_at_invalid_price_rejected() -> None:
    with pytest.raises(ValueError):
        close_position(side="long", quantity=0.1, avg_entry_price=100, exit_price=-1)