from fastapi.testclient import TestClient

from app.api.server import create_app
from app.exchanges.factory import ExchangeFactory
from config import Settings


def test_live_trading_guard_blocks_state_changing_endpoints_and_persists_events(tmp_path, monkeypatch):
    def fail_if_exchange_created(*args, **kwargs):
        raise AssertionError("live-trading guard should reject before creating exchange clients")

    monkeypatch.setattr(ExchangeFactory, "get_or_create", fail_if_exchange_created)

    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "guard.sqlite3"),
            enable_live_trading=False,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )

    with TestClient(app) as client:
        requests = [
            client.post(
                "/api/v1/order",
                json={
                    "exchange": "binance_usdm",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "order_type": "market",
                    "quantity": 0.001,
                },
            ),
            client.post(
                "/api/v1/contracts/order",
                json={
                    "exchange": "binance_usdm",
                    "symbol": "BTCUSDT",
                    "intent": "open_long",
                    "quantity": 0.001,
                    "order_type": "limit",
                    "price": 100000,
                    "margin_mode": "cross",
                    "position_side": "long",
                    "leverage": 3,
                },
            ),
            client.post("/api/v1/contracts/binance_usdm/BTCUSDT/leverage?leverage=3"),
            client.delete("/api/v1/order/binance_usdm/BTCUSDT/order-123"),
            client.delete("/api/v1/orders/binance_usdm/open?symbol=BTCUSDT"),
        ]

        assert [response.status_code for response in requests] == [403, 403, 403, 403, 403]

        response = client.get("/api/v1/events/recent?category=risk&limit=10")
        assert response.status_code == 200
        events = response.json()["events"]

    assert len(events) == 5
    assert {event["event_type"] for event in events} == {"live_trading_blocked"}
    assert [event["details"]["action"] for event in events] == [
        "place_order",
        "place_contract_order",
        "set_leverage",
        "cancel_order",
        "cancel_all_orders",
    ]
    assert events[0]["exchange"] == "binance_usdm"
    assert events[1]["symbol"] == "BTCUSDT"
    assert events[3]["order_id"] == "order-123"
