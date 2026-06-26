"""Tests for position sizing calculator."""

from __future__ import annotations

import pytest

from app.engine.position_sizer import calculate_position_size


def test_basic_long_position() -> None:
    r = calculate_position_size(
        account_equity=10_000,
        entry_price=100.0,
        stop_loss_price=98.0,
        risk_pct=0.02,
        leverage=5.0,
    )
    # Risk $200 = 2% of $10k. SL distance 2/100=2%. Quantity = 200 / (0.02 * 100) = 100.
    assert r.quantity == 100.0
    assert r.notional == 10_000.0
    assert r.margin == 2_000.0
    assert abs(r.risk_amount - 200.0) < 0.01


def test_basic_short_position() -> None:
    r = calculate_position_size(
        account_equity=10_000,
        entry_price=100.0,
        stop_loss_price=102.0,
        risk_pct=0.01,
    )
    assert r.quantity == 50.0
    assert r.notional == 5_000.0


def test_min_quantity_floor() -> None:
    r = calculate_position_size(
        account_equity=10.0,
        entry_price=50_000.0,
        stop_loss_price=49_000.0,
        risk_pct=0.02,
        min_quantity=0.001,
    )
    assert r.quantity >= 0.001


def test_risk_reward_ratio_long() -> None:
    r = calculate_position_size(
        account_equity=10_000,
        entry_price=100.0,
        stop_loss_price=98.0,
        take_profit_price=104.0,
    )
    assert r.risk_reward_ratio == 2.0


def test_high_leverage_reduces_margin() -> None:
    r1 = calculate_position_size(
        account_equity=10_000,
        entry_price=100.0,
        stop_loss_price=98.0,
        leverage=1.0,
    )
    r10 = calculate_position_size(
        account_equity=10_000,
        entry_price=100.0,
        stop_loss_price=98.0,
        leverage=10.0,
    )
    assert r1.margin == r10.margin * 10


def test_zero_risk_pct_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_position_size(10_000, 100.0, 98.0, risk_pct=0.0)


def test_entry_equals_sl_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_position_size(10_000, 100.0, 100.0)


def test_negative_equity_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_position_size(-1, 100.0, 98.0)