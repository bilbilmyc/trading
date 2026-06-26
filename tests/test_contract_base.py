"""Tests for ContractExchangeBase — resolve_order_intent mapping."""

from __future__ import annotations

import pytest

from app.exchanges.base import ExchangeBase
from app.exchanges.contract_base import ContractExchangeBase
from app.models.contract import ContractOrderIntent, PositionSide


class _StubContract(ContractExchangeBase, ExchangeBase):
    def __init__(self):
        super().__init__()

    @property
    def name(self) -> str:
        return "stub"

    @property
    def base_url(self) -> str:
        return "https://stub"

    async def get_ticker(self, symbol):
        return {}

    async def get_klines(self, symbol, interval="1m", limit=100):
        return []

    async def get_recent_trades(self, symbol, limit=50):
        return []

    async def get_account_balance(self):
        return {}

    async def place_order(self, symbol, side, order_type, quantity, price=None):
        return {}

    async def cancel_order(self, symbol, order_id):
        return {}

    async def get_open_orders(self, symbol=None):
        return []

    async def cancel_all_orders(self, symbol=None):
        return []

    async def get_available_balances(self):
        return {}

    async def get_order(self, symbol, order_id):
        return {}

    async def subscribe_ticker(self, symbol, callback=None):
        pass

    async def unsubscribe_ticker(self, symbol):
        pass

    async def get_contract_markets(self, quote_asset="USDT", search=None, limit=200):
        return []

    async def get_fee_rate(self, symbol):
        return {"maker": 0.0, "taker": 0.0}

    async def get_positions(self, symbol=None):
        return []

    async def place_contract_order(self, **kwargs):
        return {}

    async def set_leverage(self, symbol, leverage):
        return {}


def test_open_long_resolves_to_buy_long() -> None:
    e = _StubContract()
    side, pos, reduce = e.resolve_order_intent(ContractOrderIntent.OPEN_LONG)
    assert side == "buy"
    assert pos == PositionSide.LONG
    assert reduce is False


def test_close_long_resolves_to_sell_long_reduce_only() -> None:
    e = _StubContract()
    side, pos, reduce = e.resolve_order_intent(ContractOrderIntent.CLOSE_LONG)
    assert side == "sell"
    assert pos == PositionSide.LONG
    assert reduce is True


def test_open_short_resolves_to_sell_short() -> None:
    e = _StubContract()
    side, pos, reduce = e.resolve_order_intent(ContractOrderIntent.OPEN_SHORT)
    assert side == "sell"
    assert pos == PositionSide.SHORT
    assert reduce is False


def test_close_short_resolves_to_buy_short_reduce_only() -> None:
    e = _StubContract()
    side, pos, reduce = e.resolve_order_intent(ContractOrderIntent.CLOSE_SHORT)
    assert side == "buy"
    assert pos == PositionSide.SHORT
    assert reduce is True


def test_cost_estimate_dataclass_construction() -> None:
    from app.models.contract import CostEstimate, FeeRate, LiquidityType

    c = CostEstimate(
        exchange="binance_usdm",
        symbol="BTCUSDT",
        notional=5_000.0,
        liquidity=LiquidityType.TAKER,
        fee_rate=0.0002,
        estimated_fee=1.0,
        raw_fee=FeeRate(exchange="binance_usdm", symbol="BTCUSDT", maker=0.0002, taker=0.0005),
    )
    assert c.notional == 5_000.0
    assert c.estimated_fee == 1.0


def test_cost_estimate_with_notes() -> None:
    from app.models.contract import CostEstimate, FeeRate, LiquidityType

    c = CostEstimate(
        exchange="x",
        symbol="BTCUSDT",
        notional=100.0,
        liquidity=LiquidityType.MAKER,
        fee_rate=0.0,
        estimated_fee=0.0,
        raw_fee=FeeRate(exchange="x", symbol="BTCUSDT", maker=0.0, taker=0.0),
        notes=["VIP tier 1", "BNB discount"],
    )
    assert "VIP tier 1" in c.notes


def test_fee_rate_dataclass() -> None:
    from app.models.contract import FeeRate

    f = FeeRate(exchange="binance_usdm", symbol="BTCUSDT", maker=0.0002, taker=0.0005)
    assert f.maker < f.taker


def test_liquidity_type_enum() -> None:
    from app.models.contract import LiquidityType

    assert LiquidityType.MAKER.value == "maker"
    assert LiquidityType.TAKER.value == "taker"


def test_contract_order_intent_enum_values() -> None:
    assert ContractOrderIntent.OPEN_LONG.value == "open_long"
    assert ContractOrderIntent.CLOSE_LONG.value == "close_long"
    assert ContractOrderIntent.OPEN_SHORT.value == "open_short"
    assert ContractOrderIntent.CLOSE_SHORT.value == "close_short"