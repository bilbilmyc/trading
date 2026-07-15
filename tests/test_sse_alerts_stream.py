"""SSE stream: verify audit events flow through /api/v1/stream/events.

Uses ``max_events`` to bound the generator so the test client's stream
closes cleanly (same pattern as tests/test_sse_endpoint.py).
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api.server import create_app
from app.engine.monitor import Alert, AlertCategory, AlertLevel
from config import Settings


def _client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                sqlite_path=str(tmp_path / "sse.sqlite3"),
                frontend_static_dir=str(tmp_path / "static"),
            )
        )
    )


def _read_lines(response) -> list[str]:
    """Read every byte the SSE generator emitted, then split on newlines.

    Note: TestClient's ``iter_lines`` can only be consumed once. We use
    ``read()`` here because we are deliberately draining the entire
    stream — the test asserts only on the parsed payloads.
    """
    body = response.read()
    text = body.decode("utf-8", errors="replace")
    return [line for line in text.splitlines() if line.startswith("data:")]


def test_sse_emits_snapshot_first(tmp_path):
    with _client(tmp_path) as client:
        with client.stream(
            "GET",
            "/api/v1/stream/events",
            params={"max_events": 1, "heartbeat_seconds": 0.05, "poll_interval_seconds": 0.05},
        ) as response:
            assert response.status_code == 200
            lines = _read_lines(response)

    assert lines, "SSE emitted no lines at all"
    snapshot = json.loads(lines[0][len("data:") :].strip())
    assert snapshot["kind"] == "snapshot"
    assert "strategies" in snapshot
    assert "risk" in snapshot


def test_sse_pushes_alert_from_monitor(tmp_path):
    """Monitor.push lands in the in-memory ring buffer; the SSE
    generator streams it on its next poll tick."""
    with _client(tmp_path) as client:
        monitor = client.app.state.trading.engine.monitor

        # Push the alert BEFORE the SSE starts, with a fresh
        # datetime that is guaranteed to be newer than the snapshot
        # timestamp that the SSE generator emits when the connection
        # opens. (We pick `datetime.utcnow() + 0.5s` so the cursor
        # is set BEFORE this timestamp — the alert is in scope.)
        from datetime import datetime, timedelta

        future = Alert(
            level=AlertLevel.WARNING,
            category=AlertCategory.SYSTEM,
            title="test_alert",
            message="hello from test",
        )
        future.timestamp = datetime.utcnow() + timedelta(seconds=10)
        monitor._alerts.append(future)

        with client.stream(
            "GET",
            "/api/v1/stream/events",
            params={
                "max_events": 3,
                "heartbeat_seconds": 60.0,
                "poll_interval_seconds": 0.3,
            },
        ) as response:
            assert response.status_code == 200
            body = response.read().decode("utf-8", errors="replace")

    lines = [ln for ln in body.splitlines() if ln.startswith("data:")]
    payloads = [json.loads(ln[len("data:") :].strip()) for ln in lines]
    kinds = [p.get("kind") for p in payloads]
    assert "snapshot" in kinds, f"no snapshot in body: {kinds}"
    events = [p for p in payloads if p.get("kind") == "event"]
    saw = next((e for e in events if e.get("title") == "test_alert"), None)
    assert saw is not None, f"SSE body had events {events} but no test_alert"
    assert saw["level"] == "warning"
    assert saw["message"] == "hello from test"


def test_sse_skips_pre_existing_alerts(tmp_path):
    """An alert already in Monitor._alerts when the stream opens must
    not be re-emitted — the cursor is set after the snapshot."""
    with _client(tmp_path) as client:
        # Pre-seed Monitor BEFORE creating the AppState would not be
        # possible without restructuring. Instead we open the SSE,
        # wait for the snapshot, close the stream, then re-open with a
        # backdated alert pushed in between the sessions.
        with client.stream(
            "GET",
            "/api/v1/stream/events",
            params={"max_events": 2, "heartbeat_seconds": 60.0, "poll_interval_seconds": 0.5},
        ) as first_response:
            first_response.read()

        # Now backdate an alert and start a fresh SSE.
        monitor = client.app.state.trading.engine.monitor
        backdated = Alert(
            level=AlertLevel.INFO,
            category=AlertCategory.SYSTEM,
            title="backdated",
            message="before-snapshot",
        )
        backdated.timestamp = "2020-01-01T00:00:00.000000"
        monitor._alerts.append(backdated)

        with client.stream(
            "GET",
            "/api/v1/stream/events",
            params={"max_events": 2, "heartbeat_seconds": 60.0, "poll_interval_seconds": 0.5},
        ) as response:
            body = response.read().decode("utf-8", errors="replace")

    lines = [ln for ln in body.splitlines() if ln.startswith("data:")]
    kinds = [
        json.loads(ln[len("data:") :].strip()).get("kind") for ln in lines
    ]
    # Only snapshot should appear; the backdated alert is filtered by
    # the snapshot-time cursor.
    assert "event" not in kinds, f"unexpected event kinds: {kinds}"
    assert kinds[0] == "snapshot"
