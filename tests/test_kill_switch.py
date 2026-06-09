from fastapi.testclient import TestClient

from app.api.server import create_app
from app.exchanges.factory import ExchangeFactory
from config import Settings


def test_kill_switch_status_toggle_and_audit_event(tmp_path):
    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "kill-switch.sqlite3"),
            frontend_static_dir=str(tmp_path / "static"),
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/risk/kill-switch")
        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert response.json()["trading_enabled"] is True

        response = client.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": True, "reason": "unit-test-enable"},
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is True
        assert response.json()["trading_enabled"] is False

        response = client.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": False, "reason": "unit-test-disable"},
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert response.json()["trading_enabled"] is True

        response = client.get("/api/v1/events/recent?category=risk&limit=10")
        assert response.status_code == 200
        events = response.json()["events"]

    assert [event["event_type"] for event in events] == [
        "kill_switch_enabled",
        "kill_switch_disabled",
    ]
    assert events[0]["level"] == "critical"
    assert events[0]["details"]["reason"] == "unit-test-enable"
    assert events[1]["details"]["reason"] == "unit-test-disable"


def test_kill_switch_blocks_state_changing_endpoints_before_exchange_creation(tmp_path, monkeypatch):
    def fail_if_exchange_created(*args, **kwargs):
        raise AssertionError("kill-switch guard should reject before creating exchange clients")

    monkeypatch.setattr(ExchangeFactory, "get_or_create", fail_if_exchange_created)

    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "kill-switch-guard.sqlite3"),
            enable_live_trading=True,
            frontend_static_dir=str(tmp_path / "static"),
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": True, "reason": "unit-test-stop"},
        )
        assert response.status_code == 200

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

        assert [response.status_code for response in requests] == [423, 423, 423, 423, 423]

        response = client.get("/api/v1/events/recent?event_type=kill_switch_blocked&limit=10")
        assert response.status_code == 200
        events = response.json()["events"]

    assert len(events) == 5
    assert [event["details"]["action"] for event in events] == [
        "place_order",
        "place_contract_order",
        "set_leverage",
        "cancel_order",
        "cancel_all_orders",
    ]
    assert {event["level"] for event in events} == {"critical"}
    assert events[0]["exchange"] == "binance_usdm"
    assert events[1]["symbol"] == "BTCUSDT"
    assert events[3]["order_id"] == "order-123"
