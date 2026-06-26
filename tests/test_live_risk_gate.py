"""Tests for LiveRiskGate — RiskManager's RiskGate port surface."""

from __future__ import annotations

import asyncio

import pytest

from app.engine.risk_manager import RiskConfig, RiskManager
from app.engine.pipeline_types import RiskDecision
from app.strategies.base import Signal, SignalAction


def _signal(side: SignalAction = SignalAction.BUY) -> Signal:
    return Signal(symbol="BTCUSDT", action=side, strength=0.9, quantity=0.001)


@pytest.mark.asyncio
async def test_allowed_decision_for_normal_signal() -> None:
    rm = RiskManager(RiskConfig())
    decision = await rm.check(_signal(), price=100_000.0)
    assert isinstance(decision, RiskDecision)
    assert decision.allowed is True
    assert decision.reason == "通过风控检查"


@pytest.mark.asyncio
async def test_rejects_when_position_value_exceeds_max() -> None:
    rm = RiskManager(RiskConfig(max_position_value=10_000.0))
    big = Signal(symbol="BTCUSDT", action=SignalAction.BUY, strength=0.9, quantity=1.0)
    decision = await rm.check(big, price=100_000.0)
    assert decision.allowed is False
    assert "超过限制" in decision.reason


@pytest.mark.asyncio
async def test_rejects_after_daily_loss_exceeded() -> None:
    rm = RiskManager(RiskConfig(max_daily_loss=500.0))
    rm.update_daily_pnl(-600.0)
    decision = await rm.check(_signal(), price=100_000.0)
    assert decision.allowed is False
    assert "每日最大亏损" in decision.reason


@pytest.mark.asyncio
async def test_rejects_when_drawdown_breached() -> None:
    rm = RiskManager(RiskConfig(max_drawdown_pct=0.20))
    rm.update_portfolio_value(100_000.0)  # peak
    rm.update_portfolio_value(70_000.0)  # 30% drawdown
    decision = await rm.check(_signal(), price=100_000.0)
    assert decision.allowed is False
    assert "最大回撤" in decision.reason


@pytest.mark.asyncio
async def test_rejects_when_rate_limit_exceeded() -> None:
    rm = RiskManager(RiskConfig(max_orders_per_minute=3))
    for _ in range(3):
        await rm.check(_signal(), price=100.0)
    decision = await rm.check(_signal(), price=100.0)
    assert decision.allowed is False
    assert "交易频率" in decision.reason


@pytest.mark.asyncio
async def test_advisory_sl_tp_returned_when_allowed() -> None:
    rm = RiskManager(RiskConfig(stop_loss_pct=0.05, take_profit_pct=0.10))
    decision = await rm.check(_signal(), price=100.0)
    assert decision.stop_loss == pytest.approx(95.0)
    assert decision.take_profit == pytest.approx(110.0)