"""Tests for DeepSeek and MiniMax provider classes."""

import json
from typing import Any, Dict

import httpx
import pytest

from app.engine.deepseek_provider import DeepSeekProvider
from app.engine.minimax_provider import MiniMaxProvider
from app.engine.llm_types import LLMMessage, LLMRequest
from app.engine.openai_provider import RetryPolicy


def _ok_response(content: Dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    })


async def _run(provider, handler) -> Any:
    import app.engine.openai_provider as mod

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    mod.httpx.AsyncClient = lambda timeout: real(timeout=timeout, transport=transport)
    try:
        return await provider.complete(LLMRequest(
            model="some-model",
            messages=[LLMMessage(role="user", content="hi")],
        ))
    finally:
        mod.httpx.AsyncClient = real


@pytest.mark.asyncio
async def test_deepseek_default_base_url() -> None:
    p = DeepSeekProvider(api_key="sk-test")
    assert p.name == "deepseek"
    assert "deepseek" in p._base_url.lower()


@pytest.mark.asyncio
async def test_deepseek_custom_base_url() -> None:
    p = DeepSeekProvider(api_key="sk-test", base_url="https://my-proxy.example/v1")
    assert "my-proxy" in p._base_url


@pytest.mark.asyncio
async def test_deepseek_missing_key_returns_error() -> None:
    p = DeepSeekProvider(api_key="")
    r = await p.complete(LLMRequest(
        model="deepseek-chat", messages=[LLMMessage(role="user", content="hi")]
    ))
    from app.engine.llm_types import LLMErrorKind
    assert r.is_failed
    assert r.failed.kind == LLMErrorKind.API_KEY_MISSING


@pytest.mark.asyncio
async def test_deepseek_successful_response() -> None:
    p = DeepSeekProvider(api_key="sk-test")

    def handler(req):
        # DeepSeek should hit /chat/completions on the configured host.
        assert "deepseek" in str(req.url)
        return _ok_response({
            "decision": "buy", "confidence": 0.7,
            "reason": "deepseek bullish"
        })

    r = await _run(p, handler)
    assert r.is_ok
    assert r.decided.decision == "buy"
    assert r.decided.reason == "deepseek bullish"


@pytest.mark.asyncio
async def test_minimax_default_base_url() -> None:
    p = MiniMaxProvider(api_key="k")
    assert p.name == "minimax"
    assert "minimax" in p._base_url.lower()


@pytest.mark.asyncio
async def test_minimax_custom_base_url() -> None:
    p = MiniMaxProvider(api_key="k", base_url="https://example.com/v1")
    assert "example" in p._base_url


@pytest.mark.asyncio
async def test_minimax_missing_key_returns_error() -> None:
    p = MiniMaxProvider(api_key="")
    r = await p.complete(LLMRequest(
        model="minimax-m3", messages=[LLMMessage(role="user", content="hi")]
    ))
    from app.engine.llm_types import LLMErrorKind
    assert r.is_failed
    assert r.failed.kind == LLMErrorKind.API_KEY_MISSING


@pytest.mark.asyncio
async def test_minimax_successful_response() -> None:
    p = MiniMaxProvider(api_key="k")

    def handler(req):
        assert "minimax" in str(req.url)
        return _ok_response({
            "decision": "hold", "confidence": 0.5,
            "reason": "minimax flat"
        })

    r = await _run(p, handler)
    assert r.is_ok
    assert r.decided.decision == "hold"


@pytest.mark.asyncio
async def test_both_providers_use_openai_schema() -> None:
    """Both DeepSeek and MiniMax use the same OpenAI Chat Completions
    request shape — request body should have model + messages + temperature."""
    captured = {}

    async def run_for(provider, host_fragment):
        p = provider

        def handler(req):
            captured[host_fragment] = json.loads(req.content.decode())
            return _ok_response({"decision": "buy", "confidence": 0.5, "reason": "x"})

        await _run(p, handler)

    await run_for(DeepSeekProvider(api_key="k"), "deepseek")
    await run_for(MiniMaxProvider(api_key="k"), "minimax")

    # Both payloads should have OpenAI's fields.
    for payload in captured.values():
        assert "model" in payload
        assert "messages" in payload
        assert "temperature" in payload
        assert "max_tokens" in payload
        assert payload["response_format"] == {"type": "json_object"}


def test_providers_inherit_retry_policy() -> None:
    """RetryPolicy should pass through to the underlying OpenAIProvider."""
    p = DeepSeekProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=5))
    assert p._retry.max_attempts == 5
    p2 = MiniMaxProvider(api_key="k", retry_policy=RetryPolicy(max_attempts=3))
    assert p2._retry.max_attempts == 3


def test_providers_distinct_names() -> None:
    """Two providers must be distinguishable by name field."""
    assert DeepSeekProvider(api_key="k").name == "deepseek"
    assert MiniMaxProvider(api_key="k").name == "minimax"
    assert DeepSeekProvider(api_key="k").name != MiniMaxProvider(api_key="k").name
