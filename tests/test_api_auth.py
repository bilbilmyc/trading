"""Tests for the optional API key auth dependency.

The auth layer is opt-in: when `auth_api_key` is empty (the default for
local dev), no check is performed. When set, dangerous endpoints require
`Authorization: Bearer <key>` matching the configured value.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _settings(**overrides) -> Settings:
    defaults = dict(
        sqlite_path=":memory:",
        enable_live_trading=False,
        frontend_static_dir="/tmp/static",
        llm_api_key="",
        okx_enabled=False,
        binance_enabled=False,
        binance_usdm_enabled=True,
        bitget_enabled=False,
        # Auth defaults to disabled so existing dev workflows keep working.
        auth_api_key="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_kill_switch_auth_disabled_allows_request(tmp_path) -> None:
    """When auth_api_key is empty, all requests are allowed (local dev default)."""
    with TestClient(create_app(_settings(sqlite_path=str(tmp_path / "h.sqlite3")))) as c:
        r = c.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": False, "reason": "test"},
        )
        # Auth disabled → request goes through (may fail for other reasons,
        # but not with 401).
        assert r.status_code != 401, r.text


def test_kill_switch_missing_header_returns_401(tmp_path) -> None:
    """When auth is enabled, missing Authorization header → 401."""
    with TestClient(
        create_app(
            _settings(
                sqlite_path=str(tmp_path / "h.sqlite3"),
                auth_api_key="supersecret",
            )
        )
    ) as c:
        r = c.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": False, "reason": "test"},
        )
        assert r.status_code == 401
        assert r.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_kill_switch_wrong_key_returns_401(tmp_path) -> None:
    """When auth is enabled, wrong key → 401."""
    with TestClient(
        create_app(
            _settings(
                sqlite_path=str(tmp_path / "h.sqlite3"),
                auth_api_key="supersecret",
            )
        )
    ) as c:
        r = c.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": False, "reason": "test"},
            headers={"Authorization": "Bearer wrongkey"},
        )
        assert r.status_code == 401


def test_kill_switch_correct_key_passes_auth(tmp_path) -> None:
    """When auth is enabled, correct key → request reaches the handler (non-401)."""
    with TestClient(
        create_app(
            _settings(
                sqlite_path=str(tmp_path / "h.sqlite3"),
                auth_api_key="supersecret",
            )
        )
    ) as c:
        r = c.post(
            "/api/v1/risk/kill-switch",
            json={"enabled": False, "reason": "test"},
            headers={"Authorization": "Bearer supersecret"},
        )
        # Auth passed — actual handler logic runs. We only assert it was
        # not blocked by auth (not 401).
        assert r.status_code != 401, r.text


# Endpoints that mutate state and must require auth when enabled.
# Each tuple is (method, path, json_body, description).
DANGEROUS_ENDPOINTS = [
    ("POST",   "/api/v1/risk/kill-switch",       {"enabled": False, "reason": "t"}, "kill-switch"),
    ("POST",   "/api/v1/order",                  {
        "exchange": "binance_usdm", "symbol": "BTCUSDT",
        "side": "buy", "order_type": "market", "quantity": 0.001,
    }, "place spot order"),
    ("POST",   "/api/v1/contracts/order",        {
        "exchange": "binance_usdm", "symbol": "BTCUSDT",
        "intent": "open_long", "order_type": "market", "quantity": 0.001,
    }, "place contract order"),
    ("DELETE", "/api/v1/order/binance_usdm/BTCUSDT/abc123", None, "cancel order"),
    ("DELETE", "/api/v1/orders/binance_usdm/open",          None, "cancel all"),
    ("POST",   "/api/v1/contracts/binance_usdm/BTCUSDT/leverage",
                                                  {"leverage": 3}, "set leverage"),
    ("POST",   "/api/v1/paper/reset",            {}, "paper reset"),
    ("POST",   "/api/v1/runner/start",           {}, "runner start"),
    ("POST",   "/api/v1/runner/stop",            {}, "runner stop"),
    ("POST",   "/api/v1/strategies/sma",         {
        "exchange": "binance_usdm", "symbol": "BTCUSDT", "interval": "1m",
        "short_window": 5, "long_window": 20,
    }, "create SMA strategy"),
    ("POST",   "/api/v1/ai/analyze",             {
        "exchange": "binance_usdm", "symbol": "BTCUSDT", "interval": "1h", "limit": 30,
    }, "ai analyze"),
    ("POST",   "/api/v1/positions/close",        {
        "exchange": "binance_usdm", "symbol": "BTCUSDT",
    }, "close position"),
]


@pytest.mark.parametrize(
    "method,path,body,label",
    DANGEROUS_ENDPOINTS,
    ids=[e[3] for e in DANGEROUS_ENDPOINTS],
)
def test_dangerous_endpoints_return_401_when_auth_enabled(
    tmp_path, method, path, body, label
) -> None:
    """Every state-changing endpoint must respect the auth gate.

    Asserts that missing Authorization header → 401 when `auth_api_key` is set.
    (We only test the missing-header case; the dependency is already
    proven correct for the kill-switch path, and the per-endpoint test
    would only verify that we wired `Depends(require_api_key)` — which
    this test does by exercising the gate.)
    """
    with TestClient(
        create_app(
            _settings(
                sqlite_path=str(tmp_path / "h.sqlite3"),
                auth_api_key="supersecret",
            )
        )
    ) as c:
        if method == "POST":
            r = c.post(path, json=body or {})
        elif method == "DELETE":
            r = c.delete(path)
        else:
            pytest.fail(f"unsupported method in test fixture: {method}")
        assert r.status_code == 401, f"{label}: expected 401, got {r.status_code} {r.text}"


@pytest.mark.parametrize(
    "method,path,body,label",
    DANGEROUS_ENDPOINTS,
    ids=[e[3] for e in DANGEROUS_ENDPOINTS],
)
def test_dangerous_endpoints_passthrough_when_auth_disabled(
    tmp_path, method, path, body, label
) -> None:
    """When auth_api_key is empty, all requests must NOT return 401."""
    with TestClient(
        create_app(
            _settings(
                sqlite_path=str(tmp_path / "h.sqlite3"),
                # auth_api_key left empty (default)
            )
        )
    ) as c:
        if method == "POST":
            r = c.post(path, json=body or {})
        elif method == "DELETE":
            r = c.delete(path)
        else:
            pytest.fail(f"unsupported method in test fixture: {method}")
        assert r.status_code != 401, f"{label}: auth disabled should not 401, got {r.status_code} {r.text}"
