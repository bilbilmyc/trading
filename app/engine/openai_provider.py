"""OpenAIProvider — OpenAI Chat Completions adapter.

Handles three-state errors: ApiKeyMissing, HttpError, Timeout, ParseError,
RateLimited, Network. Implements transient-only retry (5xx / timeout / network).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.engine.llm_types import (
    LLMChunk,
    LLMDecided,
    LLMError,
    LLMErrorKind,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMProvider,
)


# ── Retry policy ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: tuple = (1.0, 2.0, 4.0)

    def delay_for(self, attempt: int) -> float:
        idx = min(attempt, len(self.backoff_seconds) - 1)
        return self.backoff_seconds[idx]


# ── OpenAI adapter ───────────────────────────────────────────────────


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._retry = retry_policy or RetryPolicy()

    async def _request_once(self, request: LLMRequest) -> LLMResponse:
        if not self._api_key:
            return LLMResponse(
                failed=LLMError(
                    kind=LLMErrorKind.API_KEY_MISSING,
                    message="未配置 API Key，请设置 LLM_API_KEY。",
                    retryable=False,
                )
            )

        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.response_format_json:
            payload["response_format"] = {"type": "json_object"}

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
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
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                return LLMResponse(
                    decided=self._parse_decision(content, request.model),
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
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

    async def complete_stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        """Naive single-shot streaming for OpenAI — full response in one chunk.

        OpenAI SSE requires more careful event parsing; this returns the
        full decision as one final chunk. Adequate for the AI analyze page
        where progressive output is nice-to-have, not load-bearing.
        """
        resp = await self.complete(request)
        if resp.is_failed:
            yield LLMChunk(
                text_delta=f"[error:{resp.failed.kind.value}] {resp.failed.message}",
                is_final=True,
                response=resp,
            )
            return
        d = resp.decided
        # Yield the reason field progressively so the UI sees text.
        if d.reason:
            for i in range(0, len(d.reason), 40):
                yield LLMChunk(text_delta=d.reason[i : i + 40])
        yield LLMChunk(is_final=True, response=resp)

    @staticmethod
    def _parse_decision(raw: str, model: str) -> LLMDecided:
        """Parse OpenAI's response. Distinguishes parse failure from valid hold."""
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

        def _safe_float(v: Any) -> Optional[float]:
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


__all__ = ["OpenAIProvider", "RetryPolicy"]