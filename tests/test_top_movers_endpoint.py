"""Smoke test for /api/v1/market/top-movers.

The endpoint calls `get_ticker` per symbol on the default exchange and
serves the result from a 20s TTL cache. We don't make any real network
calls in the test — the default exchange is the dummy adapter that
returns fixed values, so the response shape and ordering are enough to
pin.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                sqlite_path=str(tmp_path / "top_movers.sqlite3"),
                frontend_static_dir=str(tmp_path / "static"),
                default_exchange="binance_usdm",
            )
        )
    )


def test_top_movers_returns_per_symbol_items(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/v1/market/top-movers")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["exchange"] == "binance_usdm"
    items = body["items"]
    assert items, "items should not be empty"
    # Items carry the standard per-symbol shape; the field can be null
    # if the adapter didn't surface a 24h change — that's fine, the
    # frontend renders an empty pill.
    for it in items:
        assert "symbol" in it
        assert "price" in it
        assert "change_pct_24h" in it


def test_top_movers_filters_to_requested_symbols(tmp_path):
    with _client(tmp_path) as client:
        response = client.get(
            "/api/v1/market/top-movers",
            params={"symbols": "BTCUSDT,ETHUSDT"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [it["symbol"] for it in body["items"]] == ["BTCUSDT", "ETHUSDT"]


def test_top_movers_caches_within_ttl(tmp_path):
    """Two reads in quick succession must hit the same cache slot —
    proves the TTL is wired up (a fresh `get_ticker` call would
    produce a new timestamp on every read)."""
    with _client(tmp_path) as client:
        first = client.get("/api/v1/market/top-movers?symbols=BTCUSDT").json()
        second = client.get("/api/v1/market/top-movers?symbols=BTCUSDT").json()
    assert first["timestamp"] == second["timestamp"]
