"""Tests for TradingGuard — the kill switch + live-trading flag port."""

from __future__ import annotations

import pytest

from app.engine.live_trading_guard import LiveTradingGuard


@pytest.mark.asyncio
async def test_open_when_both_signals_clear() -> None:
    guard = LiveTradingGuard(live_trading_enabled=True)
    assert await guard.is_open() is True


@pytest.mark.asyncio
async def test_closed_when_live_trading_disabled() -> None:
    guard = LiveTradingGuard(live_trading_enabled=False)
    assert await guard.is_open() is False


@pytest.mark.asyncio
async def test_kill_switch_disables_trading() -> None:
    guard = LiveTradingGuard(live_trading_enabled=True)
    assert await guard.is_open() is True
    guard.disable_trading()
    assert await guard.is_open() is False


@pytest.mark.asyncio
async def test_kill_switch_re_enable() -> None:
    guard = LiveTradingGuard(live_trading_enabled=True)
    guard.disable_trading()
    guard.enable_trading()
    assert await guard.is_open() is True


def test_kill_switch_is_kill_switch() -> None:
    guard = LiveTradingGuard(live_trading_enabled=True)
    assert guard.kill_switch_enabled is False
    guard.disable_trading()
    assert guard.kill_switch_enabled is True
    guard.enable_trading()
    assert guard.kill_switch_enabled is False