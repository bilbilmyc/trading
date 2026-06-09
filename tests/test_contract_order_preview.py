from typing import Any, Dict, List, Optional

from fastapi.testclient import TestClient

from app.api.server import create_app
from app.exchanges.contract_base import ContractExchangeBase
from app.exchanges.factory import ExchangeFactory
from app.models.contract import ContractOrderRequest, FeeRate, MarginMode, PositionSide
from app.models.market import ContractMarket
from config import Settings


class PreviewExchange(ContractExchangeBase):
    """用于 API 测试的合约交易所替身，不访问真实网络。"""

    def __init__(self):
        super().__init__(api_key="key", secret_key="secret")
        self.last_order: Optional[ContractOrderRequest] = None

    @property
    def name(self) -> str:
        return "binance_usdm"

    @property
    def base_url(self) -> str:
        return "https://example.test"

    async def get_account_balance(self) -> Dict[str, float]:
        return {}

    async def get_available_balances(self) -> Dict[str, float]:
        return {}

    async def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return {"order_id": order_id, "symbol": symbol}

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        return 0

    async def get_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return {"order_id": order_id, "symbol": symbol}

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        return []

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        return {"symbol": symbol, "exchange": self.name, "last_price": 100000.0}

    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 100) -> List[Dict[str, Any]]:
        return []

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        return []

    async def subscribe_ticker(self, symbol: str, callback) -> None:
        return None

    async def unsubscribe_ticker(self, symbol: str) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_contract_markets(self, quote_asset: str = "USDT") -> List[ContractMarket]:
        return []

    async def get_fee_rate(self, symbol: str) -> FeeRate:
        return FeeRate(exchange=self.name, symbol=symbol, maker=0.0002, taker=0.0005)

    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: MarginMode = MarginMode.CROSS,
        position_side: PositionSide = PositionSide.NET,
    ) -> Dict[str, Any]:
        return {"symbol": symbol, "leverage": leverage}

    async def place_contract_order(self, request: ContractOrderRequest) -> Dict[str, Any]:
        self.last_order = request
        return {
            "order_id": "exchange-order-1",
            "client_order_id": request.client_order_id,
            "status": "pending",
            "exchange": self.name,
            "symbol": request.symbol,
        }

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        return []


def test_contract_order_preview_generates_client_order_id(tmp_path, monkeypatch):
    exchange = PreviewExchange()
    monkeypatch.setattr(ExchangeFactory, "get_or_create", lambda *args, **kwargs: exchange)

    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "preview.sqlite3"),
            enable_live_trading=False,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/contracts/order/preview",
            json={
                "exchange": "binance_usdm",
                "symbol": "BTCUSDT",
                "intent": "open_long",
                "quantity": 0.002,
                "order_type": "post_only",
                "price": 100000,
                "margin_mode": "cross",
                "position_side": "long",
                "leverage": 5,
            },
        )
        assert response.status_code == 200
        preview = response.json()

        events = client.get("/api/v1/events/recent?event_type=contract_order_previewed").json()["events"]

    assert preview["client_order_id"].startswith("qt")
    assert preview["notional"] == 200.0
    assert preview["initial_margin"] == 40.0
    assert preview["fee_rate"] == 0.0002
    assert preview["estimated_fee"] == 0.04
    assert preview["reduce_only"] is False
    assert events[0]["order_id"] == preview["client_order_id"]


def test_contract_order_submission_adds_client_order_id_when_missing(tmp_path, monkeypatch):
    exchange = PreviewExchange()
    monkeypatch.setattr(ExchangeFactory, "get_or_create", lambda *args, **kwargs: exchange)

    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "submit.sqlite3"),
            enable_live_trading=True,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/contracts/order",
            json={
                "exchange": "binance_usdm",
                "symbol": "BTCUSDT",
                "intent": "open_long",
                "quantity": 0.002,
                "order_type": "market",
                "margin_mode": "cross",
                "position_side": "long",
            },
        )

    assert response.status_code == 200
    assert response.json()["client_order_id"].startswith("qt")
    assert exchange.last_order is not None
    assert exchange.last_order.client_order_id == response.json()["client_order_id"]
