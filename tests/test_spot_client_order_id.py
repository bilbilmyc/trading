"""Spot adapters must transmit our durable idempotency key to each venue."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from app.exchanges.binance import BinanceExchange
from app.exchanges.okx import OKXExchange


@pytest.mark.asyncio
async def test_binance_spot_sends_new_client_order_id(monkeypatch):
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = parse_qs(request.content.decode())
        observed["client_id"] = payload["newClientOrderId"][0]
        return httpx.Response(
            200,
            json={"orderId": 123, "clientOrderId": observed["client_id"], "status": "NEW"},
        )

    exchange = BinanceExchange(api_key="key", secret_key="secret")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test")
    monkeypatch.setattr(exchange, "_get_client", lambda: _async_value(client))

    result = await exchange.place_order(
        "BTCUSDT", "buy", "market", 0.01, client_order_id="spot-intent-binance-1"
    )

    assert observed["client_id"] == "spot-intent-binance-1"
    assert result["client_order_id"] == "spot-intent-binance-1"
    await client.aclose()


@pytest.mark.asyncio
async def test_okx_spot_sends_client_order_id(monkeypatch):
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.json() if hasattr(request, "json") else None
        # httpx.Request does not expose json(); parse its exact signed JSON bytes.
        import json

        payload = json.loads(request.content)
        observed["client_id"] = payload["clOrdId"]
        return httpx.Response(
            200,
            json={"code": "0", "data": [{"ordId": "okx-1", "clOrdId": observed["client_id"]}]},
        )

    exchange = OKXExchange(api_key="key", secret_key="secret", passphrase="pass")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test")
    monkeypatch.setattr(exchange, "_get_client", lambda: _async_value(client))

    result = await exchange.place_order(
        "BTCUSDT", "buy", "limit", 0.01, price=100.0, client_order_id="spot-intent-okx-1"
    )

    assert observed["client_id"] == "spot-intent-okx-1"
    assert result["client_order_id"] == "spot-intent-okx-1"
    await client.aclose()


async def _async_value(value):
    return value
