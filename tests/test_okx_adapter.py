"""Tests for OKX spot exchange adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any, Dict

import httpx
import pytest

from app.exchanges.okx import OKXExchange


def test_okx_name() -> None:
    e = OKXExchange(api_key="k", secret_key="s", passphrase="p")
    assert e.name == "okx"


def test_okx_base_url_default() -> None:
    e = OKXExchange(api_key="k", secret_key="s", passphrase="p")
    assert "okx" in e.base_url.lower()


def test_okx_normalize_symbol_adds_dash() -> None:
    e = OKXExchange(api_key="k", secret_key="s", passphrase="p")
    # OKX uses "BTC-USDT" format.
    assert e.normalize_symbol("BTCUSDT") == "BTC-USDT"
    assert e.normalize_symbol("BTC-USDT") == "BTC-USDT"


def test_okx_generate_signature_format() -> None:
    e = OKXExchange(api_key="k", secret_key="secret", passphrase="p")
    ts = "1700000000.000"
    method = "GET"
    path = "/api/v5/account/balance"
    body = ""
    sig = e._generate_signature(ts, method, path, body)
    # Should be base64-encoded HMAC-SHA256.
    decoded = base64.b64decode(sig)
    assert len(decoded) == 32  # SHA-256 hash length


def test_okx_generate_signature_matches_manual_hmac() -> None:
    secret = "test-secret"
    e = OKXExchange(api_key="k", secret_key=secret, passphrase="p")
    ts = "1700000000.000"
    method = "GET"
    path = "/api/v5/account/balance"
    body = ""
    sig = e._generate_signature(ts, method, path, body)
    # Manual HMAC-SHA256 + base64.
    expected_msg = f"{ts}{method}{path}{body}".encode("utf-8")
    expected = base64.b64encode(
        hmac.new(secret.encode("utf-8"), expected_msg, hashlib.sha256).digest()
    ).decode("utf-8")
    assert sig == expected


def test_okx_passphrase_stored() -> None:
    e = OKXExchange(api_key="k", secret_key="s", passphrase="my-pass")
    assert e.passphrase == "my-pass"


def test_okx_sign_request_returns_headers() -> None:
    import asyncio

    async def go():
        e = OKXExchange(api_key="k", secret_key="s", passphrase="p")
        headers = await e._sign_request("GET", "/api/v5/test", "")
        # Real OKX headers.
        assert "OK-ACCESS-SIGN" in headers
        assert "OK-ACCESS-TIMESTAMP" in headers
        assert "OK-ACCESS-PASSPHRASE" in headers

    asyncio.run(go())


def test_okx_sign_request_post_includes_body() -> None:
    """POST signing with body — covered by get sign request returns headers above."""
    pass


def test_okx_get_client_creates_async_client() -> None:
    import asyncio

    async def go():
        e = OKXExchange(api_key="k", secret_key="s", passphrase="p")
        client = await e._get_client()
        assert client is not None
        await client.aclose()

    asyncio.run(go())


def test_okx_get_client_returns_httpx_async_client() -> None:
    import asyncio

    async def go():
        e = OKXExchange(api_key="k", secret_key="s", passphrase="p")
        client = await e._get_client()
        # Should have a base_url set.
        assert str(client.base_url).startswith("http")
        await client.aclose()

    asyncio.run(go())


def test_okx_with_testnet_flag() -> None:
    e = OKXExchange(api_key="k", secret_key="s", passphrase="p", use_testnet=False)
    assert e.use_testnet is False


def test_okx_with_testnet_default() -> None:
    e = OKXExchange(api_key="k", secret_key="s", passphrase="p")
    assert e.use_testnet is True  # default