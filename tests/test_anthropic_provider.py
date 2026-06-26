"""Tests for AnthropicProvider — Anthropic Messages API adapter."""

from __future__ import annotations

import json
from typing import Any, Dict

import httpx
import pytest

from app.engine.llm_types import (
    LLMErrorKind,
    LLMMessage,
    LLMRequest,
    LLMResponse,
)
from app.engine.openai_provider import RetryPolicy
from app.engine.anthropic_provider import AnthropicProvider


def _ok_anthropic_response(content_text: str = '{"decision":"buy","confidence":0.7,"reason":"uptrend"}') -> httpx.Response:
    body = {
        "id": "msg_abc",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content_text}],
        "model": "claude-sonnet-4-5",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    return httpx.Response(200, json=body)


def _http_error(status: int, body: str = "") -> httpx.Response:
    return httpx.Response(status, text=body or f"status {status}")


async def _run_with_mock(p: AnthropicProvider, handler) -> LLMResponse:
    import app.engine.anthropic_provider as mod

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    mod.httpx.AsyncClient = lambda timeout: real_client(timeout=timeout, transport=transport)
    try:
        return await p.complete(LLMRequest(
            model="claude-sonnet-4-5",
            messages=[LLMMessage(role="user", content="hi")],
        ))
    finally:
        mod.httpx.AsyncClient = real_client


@pytest.mark.asyncio
async def test_missing_api_key_returns_error() -> None:
    p = AnthropicProvider(api_key="")
    resp = await _run_with_mock(p, lambda req: _ok_anthropic_response())
    assert resp.is_failed
    assert resp.failed.kind == LLMErrorKind.API_KEY_MISSING
    assert resp.failed.retryable is False


@pytest.mark.asyncio
async def test_parses_anthropic_content_array() -> None:
    p = AnthropicProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    resp = await _run_with_mock(p, lambda req: _ok_anthropic_response())
    assert resp.is_ok
    assert resp.decided.decision == "buy"
    assert resp.decided.confidence == 0.7
    assert "uptrend" in resp.decided.reason
    assert resp.prompt_tokens == 100
    assert resp.completion_tokens == 50


@pytest.mark.asyncio
async def test_request_shape_uses_anthropic_headers_and_endpoint() -> None:
    p = AnthropicProvider(api_key="test-key-123")
    captured: Dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.content.decode())
        return _ok_anthropic_response()

    resp = await _run_with_mock(p, handler)
    assert resp.is_ok

    assert "anthropic.com" in captured["url"]
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "test-key-123"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in captured["headers"]


@pytest.mark.asyncio
async def test_system_message_extracted_to_top_level_field() -> None:
    p = AnthropicProvider(api_key="k")
    captured: Dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return _ok_anthropic_response()

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    import app.engine.anthropic_provider as mod
    mod.httpx.AsyncClient = lambda timeout: real_client(timeout=timeout, transport=transport)
    try:
        await p.complete(LLMRequest(
            model="claude-sonnet-4-5",
            messages=[
                LLMMessage(role="system", content="你是交易分析师"),
                LLMMessage(role="user", content="hi"),
            ],
        ))
    finally:
        mod.httpx.AsyncClient = real_client

    body = captured["body"]
    assert body["system"] == "你是交易分析师"  # top-level system string
    assert all(m["role"] != "system" for m in body["messages"])
    assert body["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_no_system_message_omits_field() -> None:
    p = AnthropicProvider(api_key="k")
    captured: Dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return _ok_anthropic_response()

    await _run_with_mock(p, handler)
    assert "system" not in captured["body"]


@pytest.mark.asyncio
async def test_4xx_returns_http_error_not_retryable() -> None:
    p = AnthropicProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=(0,)))
    captured = {"count": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["count"] += 1
        return _http_error(401, "bad api key")

    resp = await _run_with_mock(p, handler)
    assert resp.is_failed
    assert resp.failed.kind == LLMErrorKind.HTTP_ERROR
    assert resp.failed.status_code == 401
    assert captured["count"] == 1  # no retry on 4xx


@pytest.mark.asyncio
async def test_5xx_retries_then_succeeds() -> None:
    p = AnthropicProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0, 0, 0)))
    captured = {"count": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["count"] += 1
        if captured["count"] < 2:
            return _http_error(529, "overloaded")
        return _ok_anthropic_response()

    resp = await _run_with_mock(p, handler)
    assert resp.is_ok
    assert captured["count"] == 2


@pytest.mark.asyncio
async def test_429_is_rate_limited() -> None:
    p = AnthropicProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    resp = await _run_with_mock(p, lambda req: _http_error(429, "rate limited"))
    assert resp.is_failed
    assert resp.failed.kind == LLMErrorKind.RATE_LIMITED
    assert resp.failed.retryable is True


@pytest.mark.asyncio
async def test_429_retries_until_quota_exhausted() -> None:
    p = AnthropicProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0, 0, 0)))
    captured = {"count": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["count"] += 1
        return _http_error(429, "rate limited")

    resp = await _run_with_mock(p, handler)
    assert resp.is_failed
    assert captured["count"] == 3


@pytest.mark.asyncio
async def test_request_includes_max_tokens_field() -> None:
    """Anthropic requires max_tokens; we should pass it through."""
    p = AnthropicProvider(api_key="k")
    captured: Dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return _ok_anthropic_response()

    await _run_with_mock(p, handler)
    assert captured["body"]["max_tokens"] == 2048  # default from LLMRequest


@pytest.mark.asyncio
async def test_parse_failure_yields_hold_decided_with_note() -> None:
    p = AnthropicProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    bad_json = '{"decision":"buy","conf'  # truncated JSON
    resp = await _run_with_mock(p, lambda req: _ok_anthropic_response(bad_json))
    assert resp.is_ok
    assert resp.decided.decision == "hold"
    assert "格式异常" in resp.decided.reason
    assert resp.decided.risk_level == "high"


@pytest.mark.asyncio
async def test_markdown_fence_stripped_from_text_block() -> None:
    p = AnthropicProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    fenced = '```json\n{"decision":"sell","confidence":0.8,"reason":"breakdown"}\n```'
    resp = await _run_with_mock(p, lambda req: _ok_anthropic_response(fenced))
    assert resp.is_ok
    assert resp.decided.decision == "sell"
    assert resp.decided.confidence == 0.8