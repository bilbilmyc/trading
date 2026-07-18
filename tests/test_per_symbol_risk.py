"""Tests for per-symbol risk controls — leverage caps + position size caps.

Default per-symbol caps live in settings. The RiskGate rejects orders that
exceed them. Caps are configured via Settings.symbol_overrides.
"""

from __future__ import annotations

import pytest

from app.engine.risk_manager import RiskConfig, RiskManager
from app.strategies.base import Signal, SignalAction


def _signal(action: SignalAction = SignalAction.BUY) -> Signal:
    return Signal(symbol="BTCUSDT", action=action, strength=0.9, quantity=0.001)


def _risk_manager(caps: dict | None = None) -> RiskManager:
    """RiskManager with optional per-symbol caps."""
    cfg = RiskConfig(
        max_position_value=10_000_000.0,  # global default: very high
        max_orders_per_minute=100,         # very high so rate doesn't trigger
        max_leverage=0.0,                    # each test below controls its own leverage cap
        symbol_overrides=caps or {},
    )
    return RiskManager(cfg)


@pytest.mark.asyncio
async def test_btc_capped_at_5x_leverage_otherwise_rejected() -> None:
    rm = _risk_manager({"BTCUSDT": {"max_leverage": 5.0}})
    # Manual leverage on signal → 10x exceeds 5x cap.
    decision = await rm.check_with_leverage(_signal(), price=100_000.0, leverage=10.0)
    assert decision.allowed is False
    assert "leverage" in decision.reason.lower()


@pytest.mark.asyncio
async def test_btc_within_5x_leverage_passes() -> None:
    rm = _risk_manager({"BTCUSDT": {"max_leverage": 5.0}})
    decision = await rm.check_with_leverage(_signal(), price=100_000.0, leverage=3.0)
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_eth_capped_at_3x() -> None:
    rm = _risk_manager({"ETHUSDT": {"max_leverage": 3.0}})
    decision = await rm.check_with_leverage(
        Signal(symbol="ETHUSDT", action=SignalAction.BUY, strength=0.9, quantity=0.01),
        price=4_000.0,
        leverage=5.0,
    )
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_unknown_symbol_uses_global_default() -> None:
    """No override → no leverage cap; only global checks apply."""
    rm = _risk_manager({"BTCUSDT": {"max_leverage": 5.0}})
    decision = await rm.check_with_leverage(
        Signal(symbol="NEWUSDT", action=SignalAction.BUY, strength=0.9, quantity=0.01),
        price=1.0,
        leverage=100.0,
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_per_symbol_position_cap() -> None:
    rm = _risk_manager({"BTCUSDT": {"max_position_value": 5_000.0}})
    # quantity=1, price=10000 → notional 10000 > 5000 cap.
    decision = await rm.check_with_leverage(
        Signal(symbol="BTCUSDT", action=SignalAction.BUY, strength=0.9, quantity=1.0),
        price=10_000.0,
        leverage=1.0,
    )
    assert decision.allowed is False
    assert "position" in decision.reason.lower() or "value" in decision.reason.lower()


@pytest.mark.asyncio
async def test_no_leverage_provided_skips_leverage_check() -> None:
    rm = _risk_manager({"BTCUSDT": {"max_leverage": 1.0}})  # only spot
    # No leverage arg → skip leverage check, only global position check.
    decision = await rm.check_with_leverage(
        Signal(symbol="BTCUSDT", action=SignalAction.BUY, strength=0.9, quantity=0.001),
        price=100.0,
    )
    assert decision.allowed is True
