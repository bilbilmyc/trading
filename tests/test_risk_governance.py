"""Targeted regression tests for the phase-4 unified pre-trade risk gates."""

from datetime import UTC, datetime

import pytest

from app.core.sqlite_store import SQLiteStore
from app.engine.risk_manager import RiskConfig, RiskManager
from app.strategies.base import Signal, SignalAction


def _signal(symbol: str = "BTCUSDT") -> Signal:
    return Signal(symbol=symbol, action=SignalAction.BUY, strength=0.9, quantity=1.0)


@pytest.mark.asyncio
async def test_blacklist_rejection_does_not_consume_frequency_slot() -> None:
    manager = RiskManager(
        RiskConfig(
            max_position_value=10_000.0,
            max_orders_per_minute=1,
            blocked_symbols=("DOGEUSDT",),
        )
    )

    blocked, reason = await manager.check_order("dogeusdt", "buy", 1.0, 1.0)
    permitted, permitted_reason = await manager.check_order("BTCUSDT", "buy", 1.0, 1.0)

    assert blocked is False
    assert "黑名单" in reason
    assert permitted is True
    assert permitted_reason == "通过风控检查"


@pytest.mark.asyncio
async def test_global_and_symbol_leverage_caps_share_one_pretrade_check() -> None:
    manager = RiskManager(
        RiskConfig(
            max_position_value=10_000.0,
            max_orders_per_minute=10,
            max_leverage=5.0,
            symbol_overrides={"btcusdt": {"max_leverage": 3.0}},
        )
    )

    btc = await manager.check_with_leverage(_signal(), price=100.0, leverage=4.0)
    eth = await manager.check_with_leverage(_signal("ETHUSDT"), price=100.0, leverage=6.0)
    allowed = await manager.check_with_leverage(_signal("ETHUSDT"), price=100.0, leverage=5.0)

    assert btc.allowed is False
    assert "单品种最大杠杆" in btc.reason
    assert eth.allowed is False
    assert "全局最大杠杆" in eth.reason
    assert allowed.allowed is True


@pytest.mark.asyncio
async def test_loss_circuit_and_utc_window_block_before_rate_limit() -> None:
    manager = RiskManager(
        RiskConfig(
            max_position_value=10_000.0,
            max_orders_per_minute=1,
            max_consecutive_losses=2,
            trading_start_hour_utc=9,
            trading_end_hour_utc=17,
        )
    )
    outside, outside_reason = await manager.check_order(
        "BTCUSDT", "buy", 1.0, 1.0, now=datetime(2026, 7, 18, 8, tzinfo=UTC)
    )
    manager.update_daily_pnl(-10.0)
    manager.update_daily_pnl(-20.0)
    streak, streak_reason = await manager.check_order(
        "BTCUSDT", "buy", 1.0, 1.0, now=datetime(2026, 7, 18, 10, tzinfo=UTC)
    )

    assert outside is False
    assert "交易时段" in outside_reason
    assert streak is False
    assert "连续亏损" in streak_reason


def test_daily_notional_reservation_is_atomic_and_idempotent(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "risk.sqlite3")
    try:
        assert store.reserve_risk_daily_notional(
            client_order_id="risk-1",
            budget_date="2026-07-18",
            notional=60.0,
            maximum_notional=100.0,
            created_at="2026-07-18T00:00:00+00:00",
        ) == (True, 0.0, False)
        assert store.reserve_risk_daily_notional(
            client_order_id="risk-1",
            budget_date="2026-07-18",
            notional=60.0,
            maximum_notional=100.0,
            created_at="2026-07-18T00:01:00+00:00",
        ) == (True, 0.0, True)
        assert store.reserve_risk_daily_notional(
            client_order_id="risk-2",
            budget_date="2026-07-18",
            notional=41.0,
            maximum_notional=100.0,
            created_at="2026-07-18T00:02:00+00:00",
        ) == (False, 60.0, False)
    finally:
        store.close()
