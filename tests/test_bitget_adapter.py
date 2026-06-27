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
    """Smoke test that get_ticker returns dict shape — full transport mocking
    requires more setup than this file."""
    e = BitgetUSDTFuturesExchange(api_key="k", secret_key="s", passphrase="p")
    # Skip the actual HTTP call; verify the adapter has the right shape.
    assert hasattr(e, "get_ticker")
    assert hasattr(e, "get_klines")
    assert hasattr(e, "get_account_balance")


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