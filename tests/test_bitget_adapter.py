"""Tests for Bitget exchange adapter — public market data and signing."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import b64encode
from typing import Any, Dict
from unittest.mock import AsyncMock

import httpx
import pytest

from app.exchanges.bitget_usdt_futures import BitgetUSDTFuturesExchange


def _sign(secret: str, ts: str, method: str, path: str, body: str) -> str:
    msg = f"{ts}{method.upper()}{path}{body}"
    return b64encode(
        hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")


def _ok_response(body: Dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def test_bitget_exchange_name() -> None:
    e = BitgetUSDTFuturesExchange(api_key="k", secret_key="s", passphrase="p")
    assert e.name == "bitget_usdt_futures"


def test_bitget_exchange_base_url_default() -> None:
    e = BitgetUSDTFuturesExchange(api_key="k", secret_key="s", passphrase="p")
    assert "bitget" in e.base_url.lower()


def test_bitget_exchange_base_url_override() -> None:
    e = BitgetUSDTFuturesExchange(
        api_key="k", secret_key="s", passphrase="p", use_testnet=False
    )
    assert e.base_url != ""


def test_bitget_signing_helper() -> None:
    e = BitgetUSDTFuturesExchange(api_key="k", secret_key="secret", passphrase="p")
    sig = e._sign("1700000000000", "GET", "/api/v2/mix/market/tickers", "")
    assert isinstance(sig, str)
    assert len(sig) > 0


def test_bitget_signing_matches_reference() -> None:
    secret = "test-secret"
    e = BitgetUSDTFuturesExchange(api_key="k", secret_key=secret, passphrase="p")
    ts = "1700000000000"
    path = "/api/v2/mix/market/tickers"
    sig = e._sign(ts, "GET", path, "")
    expected = _sign(secret, ts, "GET", path, "")
    assert sig == expected


@pytest.mark.asyncio
async def test_bitget_get_ticker_uses_path_symbol_query() -> None:
    e = BitgetUSDTFuturesExchange(api_key="k", secret_key="s", passphrase="p")
    captured: Dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        return _ok_response({"code": "00000", "data": [{"lastPr": "100.0", "symbol": "BTCUSDT"}]})

    import app.exchanges.bitget_usdt_futures as mod
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        ticker = await e.get_ticker("BTCUSDT")
    finally:
        mod.httpx.AsyncClient = real

    # URL contains symbol parameter.
    assert "symbol=BTCUSDT" in captured["url"]
    assert ticker["last_price"] == 100.0
    assert ticker["exchange"] == "bitget_usdt_futures"


@pytest.mark.asyncio
async def test_bitget_get_ticker_handles_error_response() -> None:
    e = BitgetUSDTFuturesExchange(api_key="k", secret_key="s", passphrase="p")

    def handler(req: httpx.Request) -> httpx.Response:
        return _ok_response({"code": "40001", "msg": "invalid symbol"}, status=200)

    import app.exchanges.bitget_usdt_futures as mod
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        ticker = await e.get_ticker("XXX")
    finally:
        mod.httpx.AsyncClient = real

    # Error path: still returns a dict.
    assert isinstance(ticker, dict)


@pytest.mark.asyncio
async def test_bitget_get_account_balance_unauthorized() -> None:
    e = BitgetUSDTFuturesExchange(api_key="k", secret_key="s", passphrase="p")

    def handler(req: httpx.Request) -> httpx.Response:
        return _ok_response({"code": "401", "msg": "unauthorized"}, status=200)

    import app.exchanges.bitget_usdt_futures as mod
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        result = await e.get_account_balance()
    finally:
        mod.httpx.AsyncClient = real

    # Should return empty dict on auth failure.
    assert isinstance(result, dict)


def test_bitget_exchange_with_testnet_flag() -> None:
    e = BitgetUSDTFuturesExchange(
        api_key="k", secret_key="s", passphrase="p", use_testnet=False,
    )
    assert e.use_testnet is False


def test_bitget_exchange_attributes() -> None:
    e = BitgetUSDTFuturesExchange(api_key="k", secret_key="s", passphrase="p")
    assert e.api_key == "k"
    assert e.secret_key == "s"
    assert e.passphrase == "p"
    assert e.use_testnet is True  # default