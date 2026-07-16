"""LLM types — provider protocol, three-state result, streaming chunks.

Single source of truth for everything LLM-shaped. Used by:
- LLMProvider Protocol + concrete adapters (OpenAI / Anthropic / Ollama)
- LLMAnalyzer (prompt builder + three-state classifier)
- LLMSignalFilter (Failed → reject / fail-closed)
- CompositeObserver (Failed → error_event, not risk_rejected)
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

# ── Provider errors ──────────────────────────────────────────────────


class LLMErrorKind(str, Enum):
    API_KEY_MISSING = "api_key_missing"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    RATE_LIMITED = "rate_limited"
    NETWORK = "network"


@dataclass(frozen=True)
class LLMError:
    kind: LLMErrorKind
    message: str
    status_code: int | None = None
    retryable: bool = False


# ── Three-state result ──────────────────────────────────────────────


@dataclass(frozen=True)
class LLMDecided:
    """The LLM returned a usable decision."""

    decision: str  # "buy" | "sell" | "hold"
    confidence: float
    reason: str
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_level: str = "medium"
    risk_note: str = ""
    model: str = ""
    raw_response: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    """Tagged union — exactly one of `decided` / `failed` is populated."""

    decided: LLMDecided | None = None
    failed: LLMError | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0

    @property
    def is_ok(self) -> bool:
        return self.decided is not None

    @property
    def is_failed(self) -> bool:
        return self.failed is not None


# ── Streaming ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LLMChunk:
    """A single streaming chunk. Either text delta or a final marker."""

    text_delta: str = ""
    is_final: bool = False
    response: LLMResponse | None = None


# ── Message shape (OpenAI-compatible) ────────────────────────────────


@dataclass(frozen=True)
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMRequest:
    """A single provider call."""

    model: str
    messages: Sequence[LLMMessage]
    temperature: float = 0.3
    max_tokens: int = 2048
    response_format_json: bool = True
    extra: Mapping[str, Any] = field(default_factory=dict)


# ── Provider protocol ────────────────────────────────────────────────


class LLMProvider(Protocol):
    """Port interface for any OpenAI-compatible (or future Anthropic) backend."""

    name: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    def complete_stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]: ...


__all__ = [
    "LLMErrorKind",
    "LLMError",
    "LLMDecided",
    "LLMResponse",
    "LLMChunk",
    "LLMMessage",
    "LLMRequest",
    "LLMProvider",
]
