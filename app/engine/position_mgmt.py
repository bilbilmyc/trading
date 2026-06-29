"""Position management helpers — mark-to-market + close logic.

The TradingEngine already has a PositionManager for in-memory positions.
This module adds the *API-facing* helpers used by the trade panel's
"Close" button and by the periodic mark-to-market loop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionSnapshot:
    symbol: str
    side: str            # "long" | "short"
    quantity: float
    avg_entry_price: float
    mark_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    realized_pnl: float   # cumulative since open


@dataclass
class CloseResult:
    realized_pnl: float
    exit_price: float
    exit_quantity: float
    remaining_quantity: float


def mark_to_market(
    *,
    symbol: str,
    side: str,
    quantity: float,
    avg_entry_price: float,
    mark_price: float,
    realized_pnl: float = 0.0,
) -> PositionSnapshot:
    """Compute current position state at a given mark price."""
    if quantity <= 0 or avg_entry_price <= 0:
        return PositionSnapshot(
            symbol=symbol,
            side=side,
            quantity=0.0,
            avg_entry_price=0.0,
            mark_price=mark_price,
            unrealized_pnl=0.0,
            unrealized_pnl_pct=0.0,
            realized_pnl=realized_pnl,
        )
    direction = 1 if side.lower() == "long" else -1
    unrealized = (mark_price - avg_entry_price) * quantity * direction
    pnl_pct = unrealized / (avg_entry_price * quantity)
    return PositionSnapshot(
        symbol=symbol,
        side=side,
        quantity=quantity,
        avg_entry_price=avg_entry_price,
        mark_price=mark_price,
        unrealized_pnl=unrealized,
        unrealized_pnl_pct=pnl_pct,
        realized_pnl=realized_pnl,
    )


def close_position(
    *,
    side: str,
    quantity: float,
    avg_entry_price: float,
    exit_price: float,
    realized_pnl_so_far: float = 0.0,
    close_quantity: float | None = None,
) -> CloseResult:
    """Close (or partially close) a position at `exit_price`."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if exit_price <= 0:
        raise ValueError("exit_price must be positive")
    close_qty = quantity if close_quantity is None else min(close_quantity, quantity)
    if close_qty <= 0:
        raise ValueError("close_quantity must be positive")
    direction = 1 if side.lower() == "long" else -1
    pnl = (exit_price - avg_entry_price) * close_qty * direction
    remaining = quantity - close_qty
    return CloseResult(
        realized_pnl=pnl,
        exit_price=exit_price,
        exit_quantity=close_qty,
        remaining_quantity=round(max(0.0, remaining), 8),
    )


__all__ = ["PositionSnapshot", "CloseResult", "mark_to_market", "close_position"]
