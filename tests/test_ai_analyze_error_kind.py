"""Tests for /api/v1/ai/analyze — error_kind is exposed in response.

When LLM_API_KEY is not configured, the endpoint must surface the
API_KEY_MISSING error_kind so the frontend can render a "未配置"
message instead of a generic error.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _settings_no_llm(**overrides) -> Settings:
    defaults = dict(
        sqlite_path=":memory:",
        enable_live_trading=False,
        frontend_static_dir="/tmp/static",
        llm_api_key="",  # not configured
        # All data sources disabled so the endpoint returns 404 — proves the
        # caller routed through state.data_sources (not legacy exchanges dict).
        okx_enabled=False,
        binance_enabled=False,
        bitget_enabled=False,
        okx_swap_enabled=False,
        binance_usdm_enabled=False,
        bitget_usdt_futures_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _settings_with_source(**overrides) -> Settings:
    """Build settings with one data source enabled but no API key."""
    defaults = dict(
        sqlite_path=":memory:",
        enable_live_trading=False,
        frontend_static_dir="/tmp/static",
        llm_api_key="",  # not configured
        binance_api_key="",
        binance_secret_key="",
        binance_enabled=True,
        binance_usdm_enabled=True,
        okx_enabled=False,
        bitget_enabled=False,
        okx_swap_enabled=False,
        bitget_usdt_futures_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_ai_analyze_without_key_returns_api_key_missing() -> None:
    app = create_app(_settings_with_source())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/analyze",
            json={"exchange": "binance_usdm", "symbol": "BTCUSDT", "interval": "1h", "limit": 20},
        )
        # Endpoint should not 500 — it should return a structured response.
        assert response.status_code == 200
        body = response.json()
        assert body.get("error_kind") == "api_key_missing"
        assert body.get("decision") == "hold"


def test_ai_analyze_response_shape_always_includes_error_kind() -> None:
    """error_kind is a top-level field on every response (null on success)."""
    app = create_app(_settings_with_source())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/analyze",
            json={"exchange": "binance_usdm", "symbol": "BTCUSDT", "interval": "1h", "limit": 20},
        )
        body = response.json()
        assert "error_kind" in body


def test_ai_analyze_reason_explains_missing_key() -> None:
    app = create_app(_settings_with_source())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/analyze",
            json={"exchange": "binance_usdm", "symbol": "BTCUSDT", "interval": "1h", "limit": 20},
        )
        body = response.json()
        # Frontend matches on substrings of the reason to detect "未配置".
        assert "未配置" in body.get("reason", "") or "API Key" in body.get("reason", "")


def test_ai_analyze_404_when_no_data_source() -> None:
    """Endpoint uses state.data_sources — 404 if the named source isn't enabled."""
    app = create_app(_settings_no_llm())  # all sources disabled
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/analyze",
            json={"exchange": "binance_usdm", "symbol": "BTCUSDT", "interval": "1h", "limit": 20},
        )
        assert response.status_code == 404