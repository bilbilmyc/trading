"""Targeted tests for confirmed-fill risk attribution."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.server import create_app
from app.core.sqlite_store import SQLiteStore
from app.engine.position_manager import PositionManager
from app.engine.post_trade_attribution import PostTradeRiskAttributor
from app.engine.risk_manager import RiskConfig, RiskManager
from app.models.order import Order, OrderSide, OrderStatus, OrderType
from config import Settings
from tests.test_contract_order_preview import PreviewExchange


def _order(
    client_order_id: str,
    *,
    side: OrderSide,
    quantity: float,
    price: float,
) -> Order:
    return Order(
        client_order_id=client_order_id,
        order_id=f"exchange-{client_order_id}",
        exchange="binance_usdm",
        symbol="BTCUSDT",
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        filled_quantity=quantity,
        avg_fill_price=price,
        status=OrderStatus.FILLED,
    )


@pytest.mark.asyncio
async def test_confirmed_closing_fill_backwrites_loss_streak_daily_pnl_and_drawdown(
    tmp_path,
) -> None:
    store = SQLiteStore(str(tmp_path / "attribution.db"))
    positions = PositionManager()
    risk = RiskManager(RiskConfig(max_daily_loss=1_000.0, max_consecutive_losses=2))
    risk.update_portfolio_value(1_000.0)
    attributor = PostTradeRiskAttributor(positions, risk, store)

    opened = await attributor.record_order(
        _order("open-1", side=OrderSide.BUY, quantity=1.0, price=100.0)
    )
    closed = await attributor.record_order(
        _order("close-1", side=OrderSide.SELL, quantity=1.0, price=90.0)
    )

    assert opened is not None and opened.realized_pnl == 0.0
    assert closed is not None
    assert closed.realized_pnl == pytest.approx(-10.0)
    assert risk.daily_pnl == pytest.approx(-10.0)
    assert risk.consecutive_losses == 1
    assert risk.current_drawdown == pytest.approx(0.01)
    assert (
        await attributor.record_order(
            _order("close-1", side=OrderSide.SELL, quantity=1.0, price=90.0)
        )
        is None
    )


@pytest.mark.asyncio
async def test_cumulative_partial_fill_attributes_only_the_new_weighted_delta(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "partial.db"))
    positions = PositionManager()
    risk = RiskManager()
    attributor = PostTradeRiskAttributor(positions, risk, store)

    first = await attributor.record_cumulative_fill(
        attribution_id="partial-1",
        exchange="binance_usdm",
        symbol="BTCUSDT",
        side="buy",
        cumulative_quantity=1.0,
        cumulative_avg_price=100.0,
    )
    second = await attributor.record_cumulative_fill(
        attribution_id="partial-1",
        exchange="binance_usdm",
        symbol="BTCUSDT",
        side="buy",
        cumulative_quantity=2.0,
        cumulative_avg_price=110.0,
    )

    assert first is not None and first.fill_price == pytest.approx(100.0)
    assert second is not None
    assert second.filled_quantity == pytest.approx(1.0)
    assert second.fill_price == pytest.approx(120.0)
    position = await positions.get_position("binance_usdm", "BTCUSDT")
    assert position is not None
    assert position.quantity == pytest.approx(2.0)
    assert position.avg_entry_price == pytest.approx(110.0)


@pytest.mark.asyncio
async def test_attribution_checkpoint_survives_a_recreated_service(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "restart.db"))
    positions = PositionManager()
    risk = RiskManager()
    first = PostTradeRiskAttributor(positions, risk, store)
    order = _order("restart-1", side=OrderSide.BUY, quantity=1.0, price=100.0)

    assert await first.record_order(order) is not None
    recreated = PostTradeRiskAttributor(positions, risk, store)
    assert await recreated.record_order(order) is None
    position = await positions.get_position("binance_usdm", "BTCUSDT")
    assert position is not None and position.quantity == pytest.approx(1.0)


class FilledPreviewExchange(PreviewExchange):
    def __init__(self) -> None:
        super().__init__()
        self._fill_prices = iter((100.0, 90.0))

    async def get_ticker(self, symbol: str) -> dict[str, float | str]:
        return {"symbol": symbol, "exchange": self.name, "last_price": 100.0}

    async def place_contract_order(self, request):
        self.place_calls += 1
        self.last_order = request
        price = next(self._fill_prices)
        return {
            "order_id": f"filled-{self.place_calls}",
            "client_order_id": request.client_order_id,
            "status": "filled",
            "executedQty": request.quantity,
            "avgPrice": price,
        }


def test_contract_response_fill_is_immediately_attributed_to_risk_state(
    tmp_path, monkeypatch
) -> None:
    exchange = FilledPreviewExchange()
    monkeypatch.setattr(
        "app.api.server.ExchangeFactory.get_or_create", lambda *args, **kwargs: exchange
    )
    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "api-attribution.db"),
            enable_live_trading=True,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )

    with TestClient(app) as client:
        opening = client.post(
            "/api/v1/contracts/order",
            json={
                "exchange": "binance_usdm",
                "symbol": "BTCUSDT",
                "intent": "open_long",
                "quantity": 1.0,
                "order_type": "market",
                "client_order_id": "attribution-open-001",
            },
        )
        closing = client.post(
            "/api/v1/contracts/order",
            json={
                "exchange": "binance_usdm",
                "symbol": "BTCUSDT",
                "intent": "close_long",
                "quantity": 1.0,
                "order_type": "market",
                "client_order_id": "attribution-close-001",
            },
        )

        assert opening.status_code == 200
        assert closing.status_code == 200
        risk = app.state.trading.engine.risk_manager
        assert risk.daily_pnl == pytest.approx(-10.0)
        assert risk.consecutive_losses == 1
        events = client.get("/api/v1/events/recent?event_type=post_trade_risk_attributed").json()[
            "events"
        ]
        assert len(events) == 2
