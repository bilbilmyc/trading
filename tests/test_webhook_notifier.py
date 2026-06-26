"""Tests for WebhookNotifier."""

from __future__ import annotations

import json

import httpx
import pytest

from app.engine.notifier import NotificationEvent, WebhookNotifier


def _ok_response() -> httpx.Response:
    return httpx.Response(200, text="ok")


def _bad_response() -> httpx.Response:
    return httpx.Response(500, text="down")


@pytest.mark.asyncio
async def test_disabled_short_circuits() -> None:
    n = WebhookNotifier(url="http://x", enabled=False)
    result = await n.notify(NotificationEvent(title="t", message="m"))
    assert result is False
    assert n.log() == []


@pytest.mark.asyncio
async def test_no_url_when_enabled_does_not_post() -> None:
    n = WebhookNotifier(url=None, enabled=True)
    result = await n.notify(NotificationEvent(title="t", message="m"))
    assert result is False


@pytest.mark.asyncio
async def test_post_to_webhook_returns_true_on_2xx() -> None:
    n = WebhookNotifier(url="http://x", enabled=True)

    import app.engine.notifier as mod

    captured: dict = {}
    transport = httpx.MockTransport(lambda req: _capture(req, captured) or _ok_response())
    real = httpx.AsyncClient
    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        ok = await n.notify(NotificationEvent(title="t", message="m", severity="info"))
    finally:
        mod.httpx.AsyncClient = real
    assert ok is True
    assert captured["title"] == "t"
    assert captured["message"] == "m"


@pytest.mark.asyncio
async def test_post_returns_false_on_5xx() -> None:
    n = WebhookNotifier(url="http://x", enabled=True)

    import app.engine.notifier as mod

    transport = httpx.MockTransport(lambda req: _bad_response())
    real = httpx.AsyncClient
    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        ok = await n.notify(NotificationEvent(title="t", message="m"))
    finally:
        mod.httpx.AsyncClient = real
    assert ok is False
    # Failure recorded in log.
    assert any(not entry.get("ok", True) for entry in n.log())


@pytest.mark.asyncio
async def test_network_error_does_not_raise() -> None:
    n = WebhookNotifier(url="http://x", enabled=True)

    import app.engine.notifier as mod

    def handler(req):
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        ok = await n.notify(NotificationEvent(title="t", message="m"))
    finally:
        mod.httpx.AsyncClient = real
    assert ok is False


def test_configure_updates_url_and_enabled() -> None:
    n = WebhookNotifier()
    assert not n.enabled
    n.configure(url="http://x", enabled=True)
    assert n.enabled
    n.configure(enabled=False)
    assert not n.enabled


def test_log_bounded_to_max() -> None:
    import asyncio as _asyncio

    async def run():
        n = WebhookNotifier(url="http://x", enabled=True, max_log=3)

        import app.engine.notifier as mod
        transport = httpx.MockTransport(lambda req: _ok_response())
        real = httpx.AsyncClient
        mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
        try:
            for i in range(10):
                await n.notify(NotificationEvent(title=f"t{i}", message="m"))
        finally:
            mod.httpx.AsyncClient = real
        assert len(n.log()) == 3

    _asyncio.run(run())


def _capture(req: httpx.Request, into: dict) -> None:
    body = json.loads(req.content.decode())
    into.update(body)