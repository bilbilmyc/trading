"""Smoke test for /api/v1/risk/history.

The endpoint queries `events` rows where category='risk' and
event_type='snapshot'. We don't run the engine here — instead we push
two hand-crafted rows through `SQLiteStore.append_event` and verify
the endpoint reads them back in timestamp order.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                sqlite_path=str(tmp_path / "risk_history.sqlite3"),
                frontend_static_dir=str(tmp_path / "static"),
            )
        )
    )


def test_risk_history_empty_when_no_snapshots(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/v1/risk/history?minutes=30&limit=50")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshots"] == []
    assert body["count"] == 0


def test_risk_history_returns_recent_snapshots(tmp_path):
    with _client(tmp_path) as client:
        store = client.app.state.trading.store
        assert store is not None
        now = datetime.utcnow()
        # Two snapshots: one 5 min ago, one 1 min ago.
        store.append_event({
            "category": "risk",
            "event_type": "snapshot",
            "level": "info",
            "message": "risk snapshot",
            "details": {
                "daily_pnl": -10.0,
                "current_drawdown": 0.05,
                "orders_last_minute": 1,
                "max_orders_per_minute": 5,
                "total_unrealized_pnl": 250.0,
                "kill_switch_enabled": False,
            },
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
        })
        store.append_event({
            "category": "risk",
            "event_type": "snapshot",
            "level": "info",
            "message": "risk snapshot",
            "details": {
                "daily_pnl": -25.0,
                "current_drawdown": 0.10,
                "orders_last_minute": 2,
                "max_orders_per_minute": 5,
                "total_unrealized_pnl": 600.0,
                "kill_switch_enabled": True,
            },
            "timestamp": (now - timedelta(minutes=1)).isoformat(),
        })

        response = client.get("/api/v1/risk/history?minutes=30&limit=50")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    snapshots = body["snapshots"]
    # Most recent first (events store returns newest last; this endpoint
    # walks them in store order, so the older one is first).
    assert snapshots[0]["daily_pnl"] == -10.0
    assert snapshots[1]["daily_pnl"] == -25.0
    assert snapshots[1]["kill_switch_enabled"] is True


def test_risk_history_filters_by_minutes_window(tmp_path):
    with _client(tmp_path) as client:
        store = client.app.state.trading.store
        assert store is not None
        now = datetime.utcnow()
        # 90 minutes ago — outside the 30-min window.
        store.append_event({
            "category": "risk",
            "event_type": "snapshot",
            "level": "info",
            "message": "stale",
            "details": {"daily_pnl": 0.0},
            "timestamp": (now - timedelta(minutes=90)).isoformat(),
        })
        # 2 minutes ago — inside.
        store.append_event({
            "category": "risk",
            "event_type": "snapshot",
            "level": "info",
            "message": "fresh",
            "details": {"daily_pnl": -3.0},
            "timestamp": (now - timedelta(minutes=2)).isoformat(),
        })

        response = client.get("/api/v1/risk/history?minutes=30&limit=50")
    body = response.json()
    assert body["count"] == 1
    assert body["snapshots"][0]["daily_pnl"] == -3.0
