"""Tests for OllamaProvider — local Ollama chat API adapter."""

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
from app.engine.ollama_provider import OllamaProvider


def _ok_ollama_response(content_text: str = '{"decision":"buy","confidence":0.65,"reason":"rsi oversold"}') -> httpx.Response:
    body = {
        "model": "llama3.1",
        "created_at": "2026-06-26T00:00:00Z",
        "message": {"role": "assistant", "content": content_text},
        "done": True,
        "done_reason": "stop",
        "total_duration": 1234567890,
        "load_duration": 1000000,
        "prompt_eval_count": 50,
        "prompt_eval_duration": 5000000,
        "eval_count": 25,
        "eval_duration": 100000000,
    }
    return httpx.Response(200, json=body)


def _http_error(status: int, body: str = "") -> httpx.Response:
    return httpx.Response(status, text=body or f"status {status}")


async def _run_with_mock(p: OllamaProvider, handler) -> LLMResponse:
    import app.engine.ollama_provider as mod

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    mod.httpx.AsyncClient = lambda timeout: real_client(timeout=timeout, transport=transport)
    try:
        return await p.complete(LLMRequest(
            model="llama3.1",
            messages=[LLMMessage(role="user", content="hi")],
        ))
    finally:
        mod.httpx.AsyncClient = real_client


@pytest.mark.asyncio
async def test_no_api_key_required_for_local_ollama() -> None:
    """Local Ollama does not require an API key — request succeeds with empty key."""
    p = OllamaProvider(base_url="http://localhost:11434", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    resp = await _run_with_mock(p, lambda req: _ok_ollama_response())
    assert resp.is_ok
    assert resp.decided.decision == "buy"
    assert resp.decided.confidence == 0.65


@pytest.mark.asyncio
async def test_request_uses_native_api_chat_endpoint() -> None:
    p = OllamaProvider(base_url="http://localhost:11434", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    captured: Dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.content.decode())
        return _ok_ollama_response()

    resp = await _run_with_mock(p, handler)
    assert resp.is_ok
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["stream"] is False
    assert captured["body"]["model"] == "llama3.1"


@pytest.mark.asyncio
async def test_parses_message_content_from_response() -> None:
    p = OllamaProvider(base_url="http://localhost:11434", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    captured = {"count": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["count"] += 1
        return _ok_ollama_response('{"decision":"sell","confidence":0.9,"reason":"breakdown"}')

    resp = await _run_with_mock(p, handler)
    assert resp.is_ok
    assert resp.decided.decision == "sell"
    assert resp.decided.confidence == 0.9
    assert captured["count"] == 1


@pytest.mark.asyncio
async def test_extracts_token_counts_from_response() -> None:
    p = OllamaProvider(base_url="http://localhost:11434", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    resp = await _run_with_mock(p, lambda req: _ok_ollama_response())
    assert resp.prompt_tokens == 50
    assert resp.completion_tokens == 25


@pytest.mark.asyncio
async def test_404_model_not_found_returns_http_error() -> None:
    p = OllamaProvider(base_url="http://localhost:11434", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))

    def handler(req: httpx.Request) -> httpx.Response:
        return _http_error(404, "model not found")

    resp = await _run_with_mock(p, handler)
    assert resp.is_failed
    assert resp.failed.kind == LLMErrorKind.HTTP_ERROR
    assert resp.failed.status_code == 404
    assert resp.failed.retryable is False


@pytest.mark.asyncio
async def test_5xx_retries_then_gives_up() -> None:
    p = OllamaProvider(base_url="http://localhost:11434", retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0, 0, 0)))
    captured = {"count": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["count"] += 1
        return _http_error(500, "internal")

    resp = await _run_with_mock(p, handler)
    assert resp.is_failed
    assert captured["count"] == 3


@pytest.mark.asyncio
async def test_5xx_eventually_succeeds() -> None:
    p = OllamaProvider(base_url="http://localhost:11434", retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=(0, 0, 0)))
    captured = {"count": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["count"] += 1
        if captured["count"] < 3:
            return _http_error(503, "starting up")
        return _ok_ollama_response()

    resp = await _run_with_mock(p, handler)
    assert resp.is_ok
    assert captured["count"] == 3


@pytest.mark.asyncio
async def test_parse_failure_yields_hold_decided() -> None:
    p = OllamaProvider(base_url="http://localhost:11434", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    resp = await _run_with_mock(p, lambda req: _ok_ollama_response("garbage no json"))
    assert resp.is_ok
    assert resp.decided.decision == "hold"
    assert "格式异常" in resp.decided.reason
    assert resp.decided.risk_level == "high"


@pytest.mark.asyncio
async def test_markdown_fence_stripped_before_parse() -> None:
    p = OllamaProvider(base_url="http://localhost:11434", retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=(0,)))
    fenced = '```json\n{"decision":"hold","confidence":0.5,"reason":"no edge"}\n```'
    resp = await _run_with_mock(p, lambda req: _ok_ollama_response(fenced))
    assert resp.is_ok
    assert resp.decided.decision == "hold"