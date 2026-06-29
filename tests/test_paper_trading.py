"""Unit tests for the paper trading account state machine.

The account maintains:
  - cash (USDT balance, decremented by fees, incremented by realized P&L)
  - positions dict keyed by `exchange:symbol` (avg_entry_price, quantity, ...)
  - orders list (capped at 200) recording every fill

These tests exercise the state machine directly without going through the
HTTP layer (which is exercised by integration tests in
test_server_routes*.py).
"""

from __future__ import annotations

import pytest

from app.engine.paper_trading import PaperTradingAccount
from app.strategies.base import Signal, SignalAction


# ── Helpers ─────────────────────────────────────────────────────────


def _buy(symbol: str = "BTCUSDT", quantity: float = 0.1, strength: float = 1.0) -> Signal:
    return Signal(symbol=symbol, action=SignalAction.BUY, quantity=quantity, strength=strength)


def _sell(symbol: str = "BTCUSDT", quantity: float = 0.1, strength: float = 1.0) -> Signal:
    return Signal(symbol=symbol, action=SignalAction.SELL, quantity=quantity, strength=strength)


def _hold(symbol: str = "BTCUSDT") -> Signal:
    return Signal(symbol=symbol, action=SignalAction.HOLD, strength=1.0)


def _weak_buy(symbol: str = "BTCUSDT", quantity: float = 0.1) -> Signal:
    """Below the 0.5 strength threshold — not actionable."""
    return Signal(symbol=symbol, action=SignalAction.BUY, quantity=quantity, strength=0.3)


def _account(initial_cash: float = 10000.0, fee_rate: float = 0.001) -> PaperTradingAccount:
    return PaperTradingAccount(initial_cash=initial_cash, fee_rate=fee_rate)


# ── Opening positions ──────────────────────────────────────────────


def test_open_long_from_zero_creates_position() -> None:
    """A buy from a flat state opens a new long position at fill price."""
    acct = _account()
    order = acct.apply_signal("binance_usdm", "sma", _buy(), fill_price=50000.0)

    assert order is not None
    pos = acct.positions["binance_usdm:BTCUSDT"]
    assert pos["quantity"] == 0.1
    assert pos["avg_entry_price"] == 50000.0
    assert pos["realized_pnl"] == 0.0


def test_open_long_deducts_fee_from_cash() -> None:
    """Fee = abs(quantity * price) * fee_rate, deducted from cash."""
    acct = _account(initial_cash=10000.0, fee_rate=0.001)
    expected_fee = 0.1 * 50000.0 * 0.001  # 5.0
    acct.apply_signal("binance_usdm", "sma", _buy(), fill_price=50000.0)

    assert acct.cash == pytest.approx(10000.0 - expected_fee)


def test_open_short_creates_negative_quantity() -> None:
    """A sell from flat creates a position with negative quantity (short)."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _sell(), fill_price=50000.0)

    pos = acct.positions["binance_usdm:BTCUSDT"]
    assert pos["quantity"] == -0.1
    assert pos["avg_entry_price"] == 50000.0


# ── Adding to a position ───────────────────────────────────────────


def test_add_to_long_updates_avg_cost() -> None:
    """Buying more of a long position updates avg_entry_price using
    a weighted average of old + new cost."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.1), fill_price=50000.0)
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.1), fill_price=60000.0)

    pos = acct.positions["binance_usdm:BTCUSDT"]
    assert pos["quantity"] == 0.2
    # avg = (0.1*50000 + 0.1*60000) / 0.2 = 55000
    assert pos["avg_entry_price"] == pytest.approx(55000.0)


def test_add_to_short_updates_avg_cost() -> None:
    """Short adding: weighted average of short cost basis."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _sell(quantity=0.1), fill_price=50000.0)
    acct.apply_signal("binance_usdm", "sma", _sell(quantity=0.1), fill_price=40000.0)

    pos = acct.positions["binance_usdm:BTCUSDT"]
    assert pos["quantity"] == -0.2
    # avg = (0.1*50000 + 0.1*40000) / 0.2 = 45000
    assert pos["avg_entry_price"] == pytest.approx(45000.0)


# ── Closing and flipping positions ─────────────────────────────────


def test_close_long_records_realized_pnl() -> None:
    """Selling the full long at higher price realizes a profit."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.1), fill_price=50000.0)
    order = acct.apply_signal("binance_usdm", "sma", _sell(quantity=0.1), fill_price=60000.0)

    pos = acct.positions["binance_usdm:BTCUSDT"]
    assert pos["quantity"] == 0.0
    assert pos["avg_entry_price"] == 0.0  # reset on flat
    assert pos["realized_pnl"] == pytest.approx(1000.0)  # 0.1 * (60000-50000)
    assert order["realized_pnl"] == pytest.approx(1000.0)


def test_close_long_at_loss_records_negative_realized() -> None:
    """Selling a long at lower price realizes a loss."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.1), fill_price=50000.0)
    order = acct.apply_signal("binance_usdm", "sma", _sell(quantity=0.1), fill_price=40000.0)

    assert order["realized_pnl"] == pytest.approx(-1000.0)


def test_flip_long_to_short_keeps_residual_pnl() -> None:
    """Sell larger than the long position → close + open short, with
    realized PnL only on the closed portion."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.1), fill_price=50000.0)
    # Sell 0.2: closes 0.1 long + opens 0.1 short
    acct.apply_signal("binance_usdm", "sma", _sell(quantity=0.2), fill_price=60000.0)

    pos = acct.positions["binance_usdm:BTCUSDT"]
    assert pos["quantity"] == -0.1
    # Avg reset to the new short entry since it's a new direction
    assert pos["avg_entry_price"] == 60000.0
    # Realized: only the 0.1 that closed at 60000-50000 = +1000
    assert pos["realized_pnl"] == pytest.approx(1000.0)


def test_partial_close_keeps_position_open() -> None:
    """Selling half of a long position leaves the rest open and only
    realizes PnL on the closed half."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.2), fill_price=50000.0)
    acct.apply_signal("binance_usdm", "sma", _sell(quantity=0.1), fill_price=60000.0)

    pos = acct.positions["binance_usdm:BTCUSDT"]
    assert pos["quantity"] == 0.1
    assert pos["realized_pnl"] == pytest.approx(1000.0)
    # avg stays at 50000 (same direction)
    assert pos["avg_entry_price"] == 50000.0


def test_flip_short_to_long_resets_avg() -> None:
    """Buy larger than the short position closes short + opens long."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _sell(quantity=0.1), fill_price=50000.0)
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.2), fill_price=40000.0)

    pos = acct.positions["binance_usdm:BTCUSDT"]
    assert pos["quantity"] == 0.1
    assert pos["avg_entry_price"] == 40000.0  # reset to new direction
    # Realized from closing 0.1 short at (50000-40000)*0.1 = +1000
    assert pos["realized_pnl"] == pytest.approx(1000.0)


# ── Mark price & unrealized PnL ────────────────────────────────────


def test_mark_price_updates_unrealized_pnl_for_long() -> None:
    """mark_price sets current_price + unrealized PnL for longs."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.1), fill_price=50000.0)
    acct.mark_price("binance_usdm", "BTCUSDT", 55000.0)

    pos = acct.positions["binance_usdm:BTCUSDT"]
    assert pos["current_price"] == 55000.0
    # (55000 - 50000) * 0.1 = +500
    assert pos["unrealized_pnl"] == pytest.approx(500.0)


def test_mark_price_updates_unrealized_pnl_for_short() -> None:
    """For shorts, unrealized = (avg - current) * |qty|."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _sell(quantity=0.1), fill_price=50000.0)
    acct.mark_price("binance_usdm", "BTCUSDT", 40000.0)

    pos = acct.positions["binance_usdm:BTCUSDT"]
    # (50000 - 40000) * 0.1 = +1000
    assert pos["unrealized_pnl"] == pytest.approx(1000.0)


def test_mark_price_no_op_for_unknown_symbol() -> None:
    """mark_price must silently ignore symbols with no open position."""
    acct = _account()
    # Should not raise even though there's no position
    acct.mark_price("binance_usdm", "DOGEUSDT", 0.5)
    assert "binance_usdm:DOGEUSDT" not in acct.positions


# ── Guard clauses ─────────────────────────────────────────────────


def test_disabled_account_ignores_signals() -> None:
    """A disabled account must silently drop every signal (no state change)."""
    acct = _account()
    acct.enabled = False
    order = acct.apply_signal("binance_usdm", "sma", _buy(), fill_price=50000.0)

    assert order is None
    assert acct.positions == {}
    assert acct.cash == 10000.0  # unchanged
    assert acct.orders == []


def test_hold_signal_is_ignored() -> None:
    """HOLD is not actionable — apply_signal must return None."""
    acct = _account()
    order = acct.apply_signal("binance_usdm", "sma", _hold(), fill_price=50000.0)
    assert order is None
    assert acct.positions == {}


def test_weak_signal_below_threshold_is_ignored() -> None:
    """A buy/sell with strength ≤ 0.5 is not actionable."""
    acct = _account()
    order = acct.apply_signal("binance_usdm", "sma", _weak_buy(), fill_price=50000.0)
    assert order is None
    assert acct.positions == {}


@pytest.mark.parametrize("bad_price", [0.0, -1.0, -50000.0])
def test_invalid_fill_price_returns_none(bad_price: float) -> None:
    """Non-positive fill prices are rejected."""
    acct = _account()
    order = acct.apply_signal("binance_usdm", "sma", _buy(), fill_price=bad_price)
    assert order is None


# ── Reset & load_state ─────────────────────────────────────────────


def test_reset_clears_state() -> None:
    """reset() should empty positions/orders and restore cash to initial."""
    acct = _account(initial_cash=10000.0)
    acct.apply_signal("binance_usdm", "sma", _buy(), fill_price=50000.0)
    assert acct.positions  # had activity
    assert acct.orders

    acct.reset()
    assert acct.positions == {}
    assert acct.orders == []
    assert acct.cash == 10000.0


def test_reset_with_new_initial_cash() -> None:
    """reset(initial_cash=...) overrides the original initial cash."""
    acct = _account(initial_cash=10000.0)
    acct.reset(initial_cash=25000.0)
    assert acct.initial_cash == 25000.0
    assert acct.cash == 25000.0


def test_load_state_restores_account_fields() -> None:
    """load_state must rebuild positions/orders from a stored snapshot."""
    acct = _account()
    account_dict = {"initial_cash": 5000.0, "cash": 4500.0, "fee_rate": 0.002, "enabled": True}
    positions = [
        {"exchange": "binance_usdm", "symbol": "BTCUSDT",
         "quantity": 0.05, "avg_entry_price": 60000.0, "current_price": 65000.0,
         "realized_pnl": 100.0, "unrealized_pnl": 250.0, "updated_at": "2026-01-01"},
    ]
    orders = [
        {"order_id": "paper_abc", "exchange": "binance_usdm", "strategy": "sma",
         "symbol": "BTCUSDT", "side": "buy", "quantity": 0.05, "price": 60000.0,
         "fee": 0.3, "realized_pnl": 0.0, "status": "filled",
         "timestamp": "2026-01-01", "signal_metadata": {}},
    ]
    acct.load_state(account_dict, positions, orders)

    assert acct.initial_cash == 5000.0
    assert acct.cash == 4500.0
    assert acct.fee_rate == 0.002
    assert acct.positions["binance_usdm:BTCUSDT"]["quantity"] == 0.05
    assert len(acct.orders) == 1
    assert acct.orders[0]["order_id"] == "paper_abc"


# ── Order log ─────────────────────────────────────────────────────


def test_orders_capped_at_200() -> None:
    """Apply 250 signals → orders list must cap at 200 (most recent)."""
    acct = _account()
    for i in range(250):
        acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.001), fill_price=50000.0)
    assert len(acct.orders) == 200


def test_each_order_has_unique_id() -> None:
    """Order ids must be unique even on consecutive identical signals."""
    acct = _account()
    ids = set()
    for _ in range(10):
        order = acct.apply_signal("binance_usdm", "sma", _buy(), fill_price=50000.0)
        ids.add(order["order_id"])
    assert len(ids) == 10  # all unique


# ── Summary aggregation ───────────────────────────────────────────


def test_summary_aggregates_equity_and_pnl() -> None:
    """summary() should reflect: cash + unrealized = equity; total_pnl = equity - initial."""
    acct = _account(initial_cash=10000.0, fee_rate=0.0)  # zero fee simplifies math
    # Open long: cash decreases by fee (=0)
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.1), fill_price=50000.0)
    # Mark up
    acct.mark_price("binance_usdm", "BTCUSDT", 55000.0)

    summary = acct.summary()
    assert summary["initial_cash"] == 10000.0
    assert summary["cash"] == 10000.0  # no fee, no realized
    # Unrealized = (55000-50000)*0.1 = 500
    assert summary["unrealized_pnl"] == 500.0
    assert summary["equity"] == 10000.0 + 500.0
    assert summary["total_pnl"] == 500.0
    assert summary["active_positions"] == 1


def test_summary_includes_realized_pnl() -> None:
    """Realized PnL from closed trades must show up in summary."""
    acct = _account(fee_rate=0.0)
    acct.apply_signal("binance_usdm", "sma", _buy(quantity=0.1), fill_price=50000.0)
    acct.apply_signal("binance_usdm", "sma", _sell(quantity=0.1), fill_price=60000.0)

    summary = acct.summary()
    assert summary["realized_pnl"] == 1000.0
    # After close, no active position
    assert summary["active_positions"] == 0
    assert summary["unrealized_pnl"] == 0.0
    # Equity = cash (10000) + unrealized (0) = 10000
    # total_pnl = 10000 - 10000 = 0
    # But realized is +1000 (already booked into cash)
    # Hmm — cash should reflect realized: opened with 10000, closed with +1000
    # but fee is 0 in this test, so cash should be 10000 + 1000 = 11000
    # But wait, the realized is added to cash via self.cash += realized - fee
    # So after close: cash = 10000 + 1000 - 0 = 11000
    # And total_pnl = equity - initial = (11000 + 0) - 10000 = 1000
    assert summary["total_pnl"] == 1000.0


def test_summary_ignores_flat_positions() -> None:
    """A position with quantity=0 must NOT count as active."""
    acct = _account()
    acct.apply_signal("binance_usdm", "sma", _buy(), fill_price=50000.0)
    acct.apply_signal("binance_usdm", "sma", _sell(), fill_price=50000.0)

    summary = acct.summary()
    assert summary["active_positions"] == 0
    # but the position record still exists in the dict
    assert "binance_usdm:BTCUSDT" in acct.positions
