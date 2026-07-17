from typing import Any

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
        self.last_order: ContractOrderRequest | None = None
        self.place_calls = 0
        self.open_orders: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "binance_usdm"

    @property
    def base_url(self) -> str:
        return "https://example.test"

    async def get_account_balance(self) -> dict[str, float]:
        return {}

    async def get_available_balances(self) -> dict[str, float]:
        return {}

    async def place_order(self, *args, **kwargs) -> dict[str, Any]:
        raise NotImplementedError

    async def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        return {"order_id": order_id, "symbol": symbol}

    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        return 0

    async def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        return {"order_id": order_id, "symbol": symbol}

    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return self.open_orders

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "exchange": self.name, "last_price": 100000.0}

    async def get_klines(
        self, symbol: str, interval: str = "1m", limit: int = 100
    ) -> list[dict[str, Any]]:
        return []

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        return []

    async def subscribe_ticker(self, symbol: str, callback) -> None:
        return None

    async def unsubscribe_ticker(self, symbol: str) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_contract_markets(self, quote_asset: str = "USDT") -> list[ContractMarket]:
        return []

    async def get_fee_rate(self, symbol: str) -> FeeRate:
        return FeeRate(exchange=self.name, symbol=symbol, maker=0.0002, taker=0.0005)

    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: MarginMode = MarginMode.CROSS,
        position_side: PositionSide = PositionSide.NET,
    ) -> dict[str, Any]:
        return {"symbol": symbol, "leverage": leverage}

    async def place_contract_order(self, request: ContractOrderRequest) -> dict[str, Any]:
        self.place_calls += 1
        self.last_order = request
        return {
            "order_id": "exchange-order-1",
            "client_order_id": request.client_order_id,
            "status": "pending",
            "exchange": self.name,
            "symbol": request.symbol,
        }

    async def get_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
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

        events = client.get("/api/v1/events/recent?event_type=contract_order_previewed").json()[
            "events"
        ]

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


def test_contract_order_reuses_idempotency_result(tmp_path, monkeypatch):
    exchange = PreviewExchange()
    monkeypatch.setattr(ExchangeFactory, "get_or_create", lambda *args, **kwargs: exchange)
    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "idempotent.sqlite3"),
            enable_live_trading=True,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )
    payload = {
        "exchange": "binance_usdm",
        "symbol": "BTCUSDT",
        "intent": "open_long",
        "quantity": 0.002,
        "order_type": "market",
        "client_order_id": "contract-intent-001",
    }

    with TestClient(app) as client:
        first = client.post("/api/v1/contracts/order", json=payload)
        second = client.post("/api/v1/contracts/order", json=payload)
        conflicting = client.post(
            "/api/v1/contracts/order",
            json={**payload, "quantity": 0.003},
        )

    assert first.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert exchange.place_calls == 1
    assert conflicting.status_code == 409


class FailingPreviewExchange(PreviewExchange):
    async def place_contract_order(self, request: ContractOrderRequest) -> dict[str, Any]:
        self.place_calls += 1
        raise RuntimeError("simulated exchange timeout")


def test_contract_order_ambiguous_submission_is_durable(tmp_path, monkeypatch):
    exchange = FailingPreviewExchange()
    monkeypatch.setattr(ExchangeFactory, "get_or_create", lambda *args, **kwargs: exchange)
    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "unknown.sqlite3"),
            enable_live_trading=True,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )
    payload = {
        "exchange": "binance_usdm",
        "symbol": "BTCUSDT",
        "intent": "open_long",
        "quantity": 0.002,
        "order_type": "market",
        "client_order_id": "contract-unknown-001",
    }

    with TestClient(app) as client:
        response = client.post("/api/v1/contracts/order", json=payload)
        pending = client.get("/api/v1/executions/pending")
        replay = client.post("/api/v1/contracts/order", json=payload)

    assert response.status_code == 502
    assert response.json()["detail"]["reconciliation_required"] is True
    assert pending.status_code == 200
    assert pending.json()["intents"][0]["status"] == "unknown"
    assert pending.json()["intents"][0]["client_order_id"] == payload["client_order_id"]
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["reconciliation_required"] is True
    assert exchange.place_calls == 1


def test_restart_restores_unknown_intent_for_exchange_reconciliation(tmp_path, monkeypatch):
    database = tmp_path / "restart.sqlite3"
    failing = FailingPreviewExchange()
    monkeypatch.setattr(ExchangeFactory, "get_or_create", lambda *args, **kwargs: failing)
    payload = {
        "exchange": "binance_usdm",
        "symbol": "BTCUSDT",
        "intent": "open_long",
        "quantity": 0.002,
        "order_type": "market",
        "client_order_id": "contract-restart-001",
    }
    first_app = create_app(
        Settings(
            sqlite_path=str(database),
            enable_live_trading=True,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )
    with TestClient(first_app) as client:
        assert client.post("/api/v1/contracts/order", json=payload).status_code == 502

    recovered = PreviewExchange()
    recovered.open_orders = [
        {
            "order_id": "recovered-exchange-order",
            "client_order_id": payload["client_order_id"],
            "status": "open",
            "symbol": payload["symbol"],
            "side": "buy",
            "type": "market",
            "quantity": payload["quantity"],
        }
    ]
    monkeypatch.setattr(ExchangeFactory, "get_or_create", lambda *args, **kwargs: recovered)
    second_app = create_app(
        Settings(
            sqlite_path=str(database),
            enable_live_trading=True,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )
    with TestClient(second_app) as client:
        synced = client.post("/api/v1/sync/orders/binance_usdm")
        pending = client.get("/api/v1/executions/pending")

    assert synced.status_code == 200
    assert synced.json()["orders_changed"] == 1
    assert pending.json()["intents"][0]["status"] == "pending"
    assert pending.json()["intents"][0]["exchange_order_id"] == "recovered-exchange-order"


def test_reconciliation_block_rejects_new_contract_orders_and_explicit_recovery_releases_it(
    tmp_path, monkeypatch
):
    exchange = PreviewExchange()
    monkeypatch.setattr(ExchangeFactory, "get_or_create", lambda *args, **kwargs: exchange)
    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "reconciliation-api.sqlite3"),
            enable_live_trading=True,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )
    issue = {
        "issue_key": "unexpected_position:BTCUSDT",
        "kind": "unexpected_position",
        "resource": "BTCUSDT",
        "severity": "critical",
        "local": None,
        "exchange": {"quantity": 0.1},
    }
    payload = {
        "exchange": "binance_usdm",
        "symbol": "BTCUSDT",
        "intent": "open_long",
        "quantity": 0.002,
        "order_type": "market",
        "client_order_id": "reconciliation-guard-001",
    }

    with TestClient(app) as client:
        state = app.state.trading
        state.store.upsert_reconciliation_issues("binance_usdm", [issue])
        state.engine.account_reconciliation.restore(state.store.reconciliation_issues())

        status = client.get("/api/v1/reconciliation/status")
        blocked = client.post("/api/v1/contracts/order", json=payload)
        recovered = client.post(
            "/api/v1/reconciliation/binance_usdm/recover",
            json={"note": "Verified exchange positions and balance with operator."},
        )
        submitted = client.post("/api/v1/contracts/order", json=payload)

    assert status.status_code == 200
    assert status.json()["guard"]["blocked"] is True
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "account_reconciliation_blocked"
    assert exchange.place_calls == 1
    assert recovered.status_code == 200
    assert recovered.json()["released"] is True
    assert recovered.json()["resolved_issues"] == 1
    assert submitted.status_code == 200
