"""OllamaProvider — local Ollama chat API adapter.

Native Ollama endpoint at POST /api/chat. Local Ollama doesn't require
an API key, so the missing-key path returns success and the request is
just sent without Authorization header.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional

import httpx

from app.engine.llm_types import (
    LLMDecided,
    LLMError,
    LLMErrorKind,
    LLMMessage,
    LLMRequest,
    LLMResponse,
)
from app.engine.openai_provider import RetryPolicy


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 60.0,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._retry = retry_policy or RetryPolicy()

    async def _request_once(self, request: LLMRequest) -> LLMResponse:
        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/chat",
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
                return LLMResponse(
                    decided=self._parse_decision(text, request.model),
                    prompt_tokens=int(data.get("prompt_eval_count", 0)),
                    completion_tokens=int(data.get("eval_count", 0)),
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
    def _extract_text(data: Dict[str, Any]) -> str:
        msg = data.get("message", {})
        return str(msg.get("content", "")).strip()

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


__all__ = ["OllamaProvider"]