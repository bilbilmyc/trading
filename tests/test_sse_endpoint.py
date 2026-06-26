"""Tests for the SSE /api/v1/stream/events endpoint.

Uses ?max_events=1 to keep the generator bounded — the endpoint exits
after emitting one event, so the test client's stream closes cleanly.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api.server import create_app
from config import Settings


def test_sse_endpoint_returns_event_stream_content_type(tmp_path) -> None:
    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "sse.sqlite3"),
            frontend_static_dir=str(tmp_path / "static"),
        )
    )
    client = TestClient(app)
    try:
        with client.stream("GET", "/api/v1/stream/events?max_events=1&heartbeat_seconds=0.01") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert r.headers.get("cache-control") == "no-cache"
            for line in r.iter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[len("data:"):].strip())
                    assert payload is not None
                    return
    finally:
        client.close()


def test_sse_first_event_is_status_snapshot(tmp_path) -> None:
    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "snapshot.sqlite3"),
            frontend_static_dir=str(tmp_path / "static"),
        )
    )
    client = TestClient(app)
    payload = None
    try:
        with client.stream("GET", "/api/v1/stream/events?max_events=1&heartbeat_seconds=0.01") as r:
            assert r.status_code == 200
            for line in r.iter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[len("data:"):].strip())
                    break
    finally:
        client.close()

    assert payload is not None
    assert payload.get("kind") == "snapshot"
    assert "api_online" in payload
    assert "engine_running" in payload
    assert "risk" in payload
    assert "timestamp" in payload


def test_sse_snapshot_includes_kill_switch_state(tmp_path) -> None:
    app = create_app(
        Settings(
            sqlite_path=str(tmp_path / "kill.sqlite3"),
            frontend_static_dir=str(tmp_path / "static"),
            enable_live_trading=False,
        )
    )
    client = TestClient(app)
    payload = None
    try:
        with client.stream("GET", "/api/v1/stream/events?max_events=1&heartbeat_seconds=0.01") as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    payload = json.loads(line[len("data:"):].strip())
                    break
    finally:
        client.close()

    assert payload is not None
    assert payload["kill_switch_enabled"] is False
    assert payload["live_trading"] is False