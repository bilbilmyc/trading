"""Tests for OpenAIProvider — three-state result + transient-only retry."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from app.engine.llm_types import (
    LLMErrorKind,
    LLMMessage,
    LLMRequest,
)
from app.engine.openai_provider import OpenAIProvider, RetryPolicy


# ── fakes ────────────────────────────────────────────────────────────


def _make_transport(handler):
    """Build an httpx.MockTransport from a sync handler function."""
    return httpx.MockTransport(handler)


class _Recorder:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def ok(self, request: httpx.Request) -> httpx.Response:
        self.calls.append({"url": str(request.url), "headers": dict(request.headers)})
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps({
                "decision": "buy", "confidence": 0.7, "reason": "ok",
                "stop_loss": 95.0, "take_profit": 110.0,
                "risk_level": "low", "risk_note": "fine",
            })}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 34},
        })
        return httpx.Response(200, json=json.loads(body) if False else json.loads(body))


# Use direct Response not json re-load to avoid the silly double-load; rewrite:
def _ok_response() -> httpx.Response:
    body = {
        "choices": [{"message": {"content": json.dumps({
            "decision": "buy", "confidence": 0.7, "reason": "ok",
            "stop_loss": 95.0, "take_profit": 110.0,
            "risk_level": "low", "risk_note": "fine",
        })}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34},
    }
    return httpx.Response(200, json=body)


def _http_error_response(status: int, msg: str = "") -> httpx.Response:
    return httpx.Response(status, text=msg or f"status {status}")


# ── request shape ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_api_key_returns_api_key_missing_error() -> None:
    p = OpenAIProvider(api_key="")
    resp = await p.complete(LLMRequest(
        model="gpt-4o-mini",
        messages=[LLMMessage(role="user", content="hi")],
    ))
    assert resp.is_failed
    assert resp.failed.kind == LLMErrorKind.API_KEY_MISSING
    assert resp.failed.retryable is False


@pytest.mark.asyncio
async def test_4xx_returns_http_error_not_retryable() -> None:
    p = OpenAIProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0, 0, 0)))
    p._client_factory = lambda timeout: httpx.AsyncClient(
        timeout=timeout,
        transport=_make_transport(lambda req: _http_error_response(401, "unauthorized")),
    )
    # Patch: simpler — use monkeypatch via httpx.MockTransport on the call site.
    captured = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["count"] += 1
        return _http_error_response(401, "unauthorized")

    p._client = None  # reset any cached
    resp = await _run_with_mock_transport(p, handler)
    assert resp.is_failed
    assert resp.failed.kind == LLMErrorKind.HTTP_ERROR
    assert resp.failed.status_code == 401
    assert resp.failed.retryable is False
    assert captured["count"] == 1  # no retry on 4xx


@pytest.mark.asyncio
async def test_5xx_retries_then_succeeds() -> None:
    p = OpenAIProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0, 0, 0)))
    captured = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["count"] += 1
        if captured["count"] < 2:
            return _http_error_response(503, "unavailable")
        return _ok_response()

    resp = await _run_with_mock_transport(p, handler)
    assert resp.is_ok
    assert captured["count"] == 2  # one retry


@pytest.mark.asyncio
async def test_429_is_rate_limited_and_retryable() -> None:
    p = OpenAIProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0, 0, 0)))

    def handler(request: httpx.Request) -> httpx.Response:
        return _http_error_response(429, "rate limited")

    resp = await _run_with_mock_transport(p, handler)
    assert resp.is_failed
    assert resp.failed.kind == LLMErrorKind.RATE_LIMITED
    assert resp.failed.retryable is True


@pytest.mark.asyncio
async def test_parse_error_returns_hold_decided_with_note() -> None:
    p = OpenAIProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))

    def handler(request: httpx.Request) -> httpx.Response:
        # Valid HTTP, garbage content
        body = {"choices": [{"message": {"content": "this is not json {"}}], "usage": {}}
        return httpx.Response(200, json=body)

    resp = await _run_with_mock_transport(p, handler)
    # Parse failure → success shape with hold + reason explaining
    assert resp.is_ok
    assert resp.decided.decision == "hold"
    assert "格式异常" in resp.decided.reason
    assert resp.decided.risk_level == "high"


@pytest.mark.asyncio
async def test_markdown_fence_is_stripped_before_parse() -> None:
    p = OpenAIProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))

    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [{"message": {"content": '```json\n{"decision":"sell","confidence":0.9,"reason":"downtrend"}\n```'}}],
            "usage": {},
        }
        return httpx.Response(200, json=body)

    resp = await _run_with_mock_transport(p, handler)
    assert resp.is_ok
    assert resp.decided.decision == "sell"
    assert resp.decided.confidence == 0.9


@pytest.mark.asyncio
async def test_three_attempts_then_gives_up_on_5xx() -> None:
    p = OpenAIProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0, 0, 0)))
    captured = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["count"] += 1
        return _http_error_response(500, "always down")

    resp = await _run_with_mock_transport(p, handler)
    assert resp.is_failed
    assert resp.failed.retryable is True
    assert captured["count"] == 3


# ── helpers ──────────────────────────────────────────────────────────


async def _run_with_mock_transport(p: OpenAIProvider, handler) -> "LLMResponse":
    """Run provider.complete with a patched httpx transport."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def _factory(timeout):
        return real_client(timeout=timeout, transport=transport)

    # monkeypatch httpx.AsyncClient in the provider's module
    import app.engine.openai_provider as mod

    orig = mod.httpx.AsyncClient
    mod.httpx.AsyncClient = _factory
    try:
        return await p.complete(LLMRequest(
            model="gpt-4o-mini",
            messages=[LLMMessage(role="user", content="hi")],
        ))
    finally:
        mod.httpx.AsyncClient = orig