"""AnthropicProvider — Anthropic Messages API adapter.

Implements LLMProvider for Anthropic Claude models (claude-sonnet-4-5 etc.).
Distinct from OpenAI in three places: headers (x-api-key + anthropic-version),
endpoint (/v1/messages), and system message goes in a top-level `system`
field rather than as a message in the messages array.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from app.engine.llm_types import (
    LLMDecided,
    LLMError,
    LLMErrorKind,
    LLMRequest,
    LLMResponse,
)
from app.engine.openai_provider import RetryPolicy


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 30.0,
        anthropic_version: str = "2023-06-01",
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._version = anthropic_version
        self._retry = retry_policy or RetryPolicy()

    async def _request_once(self, request: LLMRequest) -> LLMResponse:
        if not self._api_key:
            return LLMResponse(
                failed=LLMError(
                    kind=LLMErrorKind.API_KEY_MISSING,
                    message="未配置 Anthropic API Key，请设置 LLM_API_KEY。",
                    retryable=False,
                )
            )

        system_parts: list[str] = []
        user_messages: list[dict[str, Any]] = []
        for m in request.messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                user_messages.append({"role": m.role, "content": m.content})

        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": user_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": self._version,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                latency_ms = int((time.monotonic() - started) * 1000)

                if resp.status_code == 429:
                    return LLMResponse(
                        failed=LLMError(
                            kind=LLMErrorKind.RATE_LIMITED,
                            message=f"rate limited (HTTP 429): {resp.text[:200]}",
                            status_code=429,
                            retryable=True,
                        ),
                        latency_ms=latency_ms,
                    )
                if resp.status_code >= 500:
                    return LLMResponse(
                        failed=LLMError(
                            kind=LLMErrorKind.HTTP_ERROR,
                            message=f"server error HTTP {resp.status_code}: {resp.text[:200]}",
                            status_code=resp.status_code,
                            retryable=True,
                        ),
                        latency_ms=latency_ms,
                    )
                if resp.status_code >= 400:
                    return LLMResponse(
                        failed=LLMError(
                            kind=LLMErrorKind.HTTP_ERROR,
                            message=f"client error HTTP {resp.status_code}: {resp.text[:200]}",
                            status_code=resp.status_code,
                            retryable=False,
                        ),
                        latency_ms=latency_ms,
                    )

                data = resp.json()
                text = self._extract_text(data)
                usage = data.get("usage", {})
                return LLMResponse(
                    decided=self._parse_decision(text, request.model),
                    prompt_tokens=int(usage.get("input_tokens", 0)),
                    completion_tokens=int(usage.get("output_tokens", 0)),
                    latency_ms=latency_ms,
                )

        except httpx.TimeoutException as exc:
            return LLMResponse(
                failed=LLMError(
                    kind=LLMErrorKind.TIMEOUT,
                    message=f"timeout after {self._timeout}s: {exc}",
                    retryable=True,
                ),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except httpx.HTTPError as exc:
            return LLMResponse(
                failed=LLMError(
                    kind=LLMErrorKind.NETWORK,
                    message=f"network error: {exc}",
                    retryable=True,
                ),
                latency_ms=int((time.monotonic() - started) * 1000),
            )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        last = LLMResponse(failed=LLMError(kind=LLMErrorKind.NETWORK, message="no attempts", retryable=False))
        for attempt in range(self._retry.max_attempts):
            last = await self._request_once(request)
            if last.is_ok or (last.failed is not None and not last.failed.retryable):
                return last
            if attempt < self._retry.max_attempts - 1:
                await asyncio.sleep(self._retry.delay_for(attempt))
        return last

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        """Pull the assistant text out of Anthropic's content[] array."""
        parts = data.get("content", [])
        texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
        return "\n".join(texts).strip()

    @staticmethod
    def _parse_decision(raw: str, model: str) -> LLMDecided:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("\n```", 1)[0].strip()
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return LLMDecided(
                decision="hold",
                confidence=0.0,
                reason=f"LLM 返回格式异常: {raw[:200]}",
                risk_level="high",
                risk_note="解析失败",
                model=model,
                raw_response=raw,
            )

        def _safe_float(v: Any) -> float | None:
            if v is None:
                return None
            try:
                f = float(v)
                return f if f > 0 else None
            except (ValueError, TypeError):
                return None

        decision = str(data.get("decision", "hold")).lower()
        if decision not in ("buy", "sell", "hold"):
            decision = "hold"

        return LLMDecided(
            decision=decision,
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
            reason=str(data.get("reason", "")),
            stop_loss=_safe_float(data.get("stop_loss")),
            take_profit=_safe_float(data.get("take_profit")),
            risk_level=str(data.get("risk_level", "medium")).lower(),
            risk_note=str(data.get("risk_note", "")),
            model=model,
            raw_response=raw,
        )


__all__ = ["AnthropicProvider"]
