"""Tests for /api/v1/sources — register/remove custom data sources."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def _settings() -> Settings:
    return Settings(
        sqlite_path=":memory:",
        enable_live_trading=False,
        frontend_static_dir="/tmp/static",
        llm_api_key="",
        okx_enabled=False,
        binance_enabled=False,
        bitget_enabled=False,
    )


def test_register_custom_source_appends_to_data_sources() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sources",
            json={
                "name": "my-venue",
                "base_url": "https://api.example.com/v1",
                "ticker_path": "/ticker",
            },
        )
        assert response.status_code == 200
        assert response.json()["name"] == "my-venue"

        listing = client.get("/api/v1/sources")
        assert listing.status_code == 200
        names = [s["name"] for s in listing.json()["sources"]]
        assert "my-venue" in names


def test_remove_custom_source() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        client.post("/api/v1/sources", json={"name": "temp", "base_url": "https://x"})
        response = client.delete("/api/v1/sources/temp")
        assert response.status_code == 200
        assert response.json()["removed"] is True

        listing = client.get("/api/v1/sources")
        names = [s["name"] for s in listing.json()["sources"]]
        assert "temp" not in names


def test_register_duplicate_name_returns_409() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        client.post("/api/v1/sources", json={"name": "dup", "base_url": "https://x"})
        response = client.post("/api/v1/sources", json={"name": "dup", "base_url": "https://y"})
        assert response.status_code == 409


def test_register_source_validates_required_fields() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sources",
            json={"name": "x"},  # missing base_url
        )
        assert response.status_code == 422


def test_custom_source_visible_via_data_sources_listing() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        client.post(
            "/api/v1/sources",
            json={"name": "ccxt-binance", "base_url": "https://ccxt.local/binance/v1"},
        )
        listing = client.get("/api/v1/sources")
        found = [s for s in listing.json()["sources"] if s["name"] == "ccxt-binance"]
        assert found
        assert found[0]["base_url"] == "https://ccxt.local/binance/v1"