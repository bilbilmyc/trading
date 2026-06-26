"""Tests for Position, Balance, Order, Market model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.balance import Balance
from app.models.position import Position
from app.models.order import Order, OrderSide, OrderStatus, OrderType
from app.models.market import Candlestick, Ticker, Trade


def test_balance_requires_currency() -> None:
    with pytest.raises(ValidationError):
        Balance(currency="", exchange="binance_usdm")


def test_balance_locked_property() -> None:
    b = Balance(currency="USDT", exchange="binance_usdm", total=100.0, available=60.0)
    assert b.locked == 40.0


def test_balance_utilization_rate() -> None:
    b = Balance(currency="USDT", exchange="binance_usdm", total=100.0, available=80.0)
    assert b.utilization_rate == 20.0


def test_balance_update_balance() -> None:
    b = Balance(currency="USDT", exchange="binance_usdm")
    b.update_balance(total=200.0, available=150.0)
    assert b.total == 200.0
    assert b.available == 150.0
    assert b.frozen == 50.0


def test_balance_serializes() -> None:
    b = Balance(currency="BTC", exchange="binance_usdm", total=1.0, available=0.5)
    d = b.model_dump()
    assert d["currency"] == "BTC"


def test_position_defaults_zero_quantity() -> None:
    p = Position(symbol="BTCUSDT", exchange="binance_usdm")
    assert p.quantity == 0.0
    assert p.side == "flat"


def test_position_long_via_positive_quantity() -> None:
    p = Position(symbol="BTCUSDT", exchange="binance_usdm", quantity=0.1, avg_entry_price=100_000.0)
    assert p.side == "long"


def test_position_short_via_negative_quantity() -> None:
    p = Position(symbol="BTCUSDT", exchange="binance_usdm", quantity=-0.1, avg_entry_price=100_000.0)
    assert p.side == "short"


def test_position_long_pnl_via_update_price() -> None:
    p = Position(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        quantity=0.1,
        avg_entry_price=100_000.0,
    )
    p.update_price(105_000.0)
    assert p.unrealized_pnl == 500.0


def test_position_short_pnl_via_update_price() -> None:
    p = Position(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        quantity=-0.1,
        avg_entry_price=100_000.0,
    )
    p.update_price(95_000.0)
    assert p.unrealized_pnl == 500.0


def test_position_long_loss() -> None:
    p = Position(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        quantity=0.1,
        avg_entry_price=100_000.0,
    )
    p.update_price(95_000.0)
    assert p.unrealized_pnl == -500.0


def test_position_update_price_recomputes_pnl() -> None:
    p = Position(symbol="BTCUSDT", exchange="binance_usdm", quantity=0.1, avg_entry_price=100_000.0)
    p.update_price(105_000.0)
    assert p.unrealized_pnl == 500.0
    p.update_price(95_000.0)
    assert p.unrealized_pnl == -500.0


def test_position_market_value() -> None:
    p = Position(symbol="BTCUSDT", exchange="binance_usdm", quantity=0.5, current_price=100.0)
    assert p.market_value == 50.0


def test_position_cost_basis() -> None:
    p = Position(symbol="BTCUSDT", exchange="binance_usdm", quantity=0.5, avg_entry_price=80.0)
    assert p.cost_basis == 40.0


def test_position_pnl_percentage() -> None:
    p = Position(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        quantity=1.0,
        avg_entry_price=100.0,
    )
    p.update_price(110.0)
    assert p.pnl_percentage == pytest.approx(10.0, rel=1e-3)


def test_order_side_enum() -> None:
    assert OrderSide.BUY.value == "buy"
    assert OrderSide.SELL.value == "sell"


def test_order_status_enum() -> None:
    assert OrderStatus.PENDING.value in ("pending", "new", "open", "")
    assert OrderStatus.FILLED.value == "filled"


def test_order_type_enum() -> None:
    assert OrderType.MARKET.value == "market"
    assert OrderType.LIMIT.value == "limit"


def test_candlestick_validation() -> None:
    c = Candlestick(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        interval="1h",
        open_time=1700000000,
        open=100,
        high=110,
        low=95,
        close=105,
        volume=1.0,
    )
    assert c.close == 105.0


def test_ticker_required_fields() -> None:
    t = Ticker(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        last_price=100.0,
        volume_24h=1000,
        quote_volume_24h=100_000,
    )
    assert t.symbol == "BTCUSDT"


def test_trade_required_fields() -> None:
    tr = Trade(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        price=100.0,
        quantity=0.1,
        side="buy",
        timestamp=1700000000,
        trade_id="t-1",
    )
    assert tr.side == "buy"


def test_order_with_minimal_fields() -> None:
    o = Order(
        symbol="BTCUSDT",
        exchange="binance_usdm",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
    )
    assert o.symbol == "BTCUSDT"