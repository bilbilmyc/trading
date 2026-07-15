"""Tests for /api/v1/bot and the engine_status['bot'] augmentation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.server import _bot_status_payload, create_app
from config import Settings


def _client(tmp_path, **overrides) -> TestClient:
    """Build a TestClient with the bot fields pre-loaded."""
    settings = Settings(
        sqlite_path=str(tmp_path / "bot-endpoint.sqlite3"),
        frontend_static_dir=str(tmp_path / "static"),
        **overrides,
    )
    app = create_app(settings)
    return TestClient(app)


def test_bot_endpoint_default_disabled_shape(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/v1/bot")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "enabled": False,
        "allowed_chat_ids": [],
        "token_tail": None,
        "quiet_hours": None,
        "min_alert_level": "warning",
        "alert_fingerprint_cooldown_seconds": 300,
    }


def test_bot_endpoint_token_tail_is_last_four_only(tmp_path):
    """The bearer secret must NEVER be exposed — only its tail."""
    bot_token = "1234567890:AAFxxxx-real-secret-1234567890ab"
    with _client(tmp_path, bot_telegram_token=bot_token) as client:
        response = client.get("/api/v1/bot")

    assert response.status_code == 200
    payload = response.json()
    # The last 4 chars of the input — `s[-4:]` on a 43-char string.
    assert payload["token_tail"] == "90ab"
    # Belt-and-suspenders: the rest of the token never appears anywhere.
    payload_text = response.text
    assert "AAFxxxx" not in payload_text
    assert "real-secret" not in payload_text


def test_bot_endpoint_short_token_returns_none(tmp_path):
    """Empty token => None; avoid leaking that the field is 'empty'."""
    with _client(tmp_path, bot_telegram_token="ab") as client:
        response = client.get("/api/v1/bot")

    assert response.json()["token_tail"] is None


def test_bot_endpoint_csv_chat_ids_parse_to_list(tmp_path):
    with _client(
        tmp_path,
        bot_enabled=True,
        bot_allowed_chat_ids="-1001234567890,42",
        bot_telegram_token="abcdefgh-real-1234",
        bot_quiet_hours="22-8",
    ) as client:
        payload = client.get("/api/v1/bot").json()

    assert payload["enabled"] is True
    assert payload["allowed_chat_ids"] == [-1001234567890, 42]
    assert payload["token_tail"] == "1234"
    assert payload["quiet_hours"] == [22, 8]


def test_engine_status_includes_bot_payload(tmp_path):
    with _client(
        tmp_path,
        bot_enabled=True,
        bot_telegram_token="abcdefgh-real-5678",
    ) as client:
        response = client.get("/api/v1/engine/status")

    assert response.status_code == 200
    payload = response.json()
    assert "bot" in payload
    assert payload["bot"]["enabled"] is True
    assert payload["bot"]["token_tail"] == "5678"


def test_payload_helper_matches_endpoint_for_default_settings():
    """The standalone endpoint and the engine_status augmentation must
    serialize the same fields — this locks the public shape."""
    settings = Settings()
    payload = _bot_status_payload(settings)
    assert set(payload.keys()) == {
        "enabled",
        "allowed_chat_ids",
        "token_tail",
        "quiet_hours",
        "min_alert_level",
        "alert_fingerprint_cooldown_seconds",
    }
    # When no token is set, tail is None (not "" or "    ").
    assert payload["token_tail"] is None
    assert payload["quiet_hours"] is None
    assert payload["allowed_chat_ids"] == []
