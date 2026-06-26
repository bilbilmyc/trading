# ADR-0002: LLM interface + Frontend multi-page modernization

**Status:** Accepted · 2026-06-26

Two-part scope: (1) restructure LLM provider + payload delivery; (2) split the cramped single-page dashboard into a multi-page application. Established through a /grilling session on 2026-06-26 — 13 design decisions walked down the tree one at a time.

## Context

Two accumulated debts surfaced from the user's review:

1. **LLM interface.** `LLMAnalyzer` is a single 440-line class hard-coded to OpenAI Chat Completions. It conflates "LLM said hold" with API errors (HTTP 4xx/5xx, timeout, parse failure all return `decision="hold"`), so callers cannot tell which is which. K-line data is shipped as 80-char-per-row plaintext (~12KB per request), no streaming, no caching, no retry policy, no cost accounting. Estimated cost at 1 strategy/5s polling: ~$54/hour input tokens alone.

2. **Frontend.** `App.tsx` is 1125 lines with 50+ `useState` calls and a 3-column grid (`360 + 1fr + 360`) that overflows. The right-side risk panel even self-admits the problem with `panel--risk { max-height: calc(100vh - 32px); overflow-y: auto; }`. No real navigation, no deep-linking, no mobile story.

## Decision

Two parallel tracks. Implementation order: **C — both tracks simultaneously**, with stable interfaces so neither blocks the other.

## Topic 1 — LLM interface

| Q | Decision |
|---|---|
| Q1 | Three-state result: `Decided(decision, confidence, reason)` \| `Failed(kind, reason)` where `kind ∈ {ApiKeyMissing, HttpError, Timeout, ParseError, RateLimited}`. Callers match on the type; impossible to confuse "LLM hold" with "API error". `LLMSignalFilter` treats `Failed` as pass-through (matches existing exception-pass semantics). `CompositeObserver` records `error_event` for `Failed`, not `risk_rejected`. |
| Q2 | Extract `LLMProvider` Protocol: `complete(messages) → LLMResponse` and `complete_stream(messages) → AsyncIterator[LLMChunk]`. Adapters: `OpenAIProvider` (current behavior), `AnthropicProvider` (future), `OllamaProvider` (future). `LLMAnalyzer` keeps prompt construction + three-state classification + metrics; provider choice is configuration. |
| Q3 | Compact K-line encoding (`t:06-26-14:00 o:65000 h:65100 l:64900 c:65050 v:12.5`, ~40 chars vs ~80) plus system/user prompt split — system message is static across requests and gets provider-side caching. Combined payload reduction: ~12KB → ~4KB per request. |
| Q4 | Streaming interface on top of the provider protocol. SSE on the wire. Both blocking `complete()` and `complete_stream()` live on the provider; analyzer picks based on call site. |
| Q8 | Fingerprint cache: key = `sha256(symbol + interval + last_candle_hash + position_signature + prompt_version)`. TTL 30 seconds. Hit returns cached `Decided`; miss calls provider and stores. Expected hit rate 30-50% on signal loops. |
| Q11 | Retry only transient errors (5xx, timeout, network): 3 attempts, exponential backoff 1s/2s/4s. 4xx fails immediately with `Failed(kind=HttpError)`. Throttling-respecting. |

## Topic 2 — Frontend multi-page

| Q | Decision |
|---|---|
| Q5+Q12 | **6 pages**: Trade / Markets / Strategies / Risk / Audit / Settings. Strategies page contains sub-tabs (LLM strategy config + LLM filter config) and can embed market data context. Settings page exposes LLM API config, exchange capabilities, runtime config — currently only via `/config` endpoint, hidden behind the scenes. |
| Q6 | **wouter** (~2KB) + persistent left sidebar on desktop, drawer sidebar below 768px. |
| Q7 | Three-tier Context: `StatusContext` (apiOnline, killSwitch, env, config — every page) + `EngineContext` (strategies, signals, events, positions, paper — Risk/Strategies/Audit) + page-local state (Trade's order form, Markets' symbol selector). |
| Q9+Q10 | **SSE for status push** (one FastAPI `StreamingResponse` endpoint streams engine status, market events, audit events at low cadence) + **WebSocket for `/ai/analyze` streaming** (used by Trade/Strategies pages; allows client-initiated cancel). |
| Q13 | Drawer sidebar on screens <768px. Pages still accessible but lower information density. |

## Reasons

**Why parallel (option C):** Both tracks have stable interfaces. LLM provider seam is a server-side refactor that doesn't break the existing `/api/v1/ai/analyze` response shape — only adds richer error reporting. Frontend multi-page consumes the existing API surface plus new SSE/WebSocket endpoints. Neither blocks the other; both can land in independent PRs.

**Why three-state instead of two-state (Ok/Err):** A two-state `Result[LLMAnalysisResult, Error]` would still let callers accidentally treat `Failed` as `Decided(decision=hold)` if they unwrap without checking. The discriminated union makes the confusion structurally impossible.

**Why compact K-line + system split together:** Compacting alone saves output tokens; system split alone saves input cache hits. Together they attack both ends of the prompt.

**Why SSE for status + WebSocket only for streaming LLM:** SSE is one-directional, simpler to operate, sufficient for "server tells client what changed". WebSocket only earns its complexity where bidirectional is needed (cancel streaming analysis).

## Consequences

- `LLMAnalyzer` shrinks; the ~440-line monolith becomes a ~150-line orchestrator that delegates to a provider.
- `LLMSignalFilter` is the only consumer that needs to know about `Failed` (treat as pass-through). Engine pipeline routes `Failed` to `error_event`, not `risk_rejected` — visible in the Audit page.
- Frontend bundle: +2KB (wouter), +2-3KB SSE client. Page-level code splits reduce initial load.
- Estimated token-cost reduction: 60-70% (compaction + system cache + fingerprint dedup + retry-on-transient only).
- New endpoints: `GET /api/v1/stream/events` (SSE), `WS /ws/ai/analyze`. Both behind existing auth pattern.

## Open follow-ups

- Concrete interface sketches (provider methods, SSE payload schema, Context shapes) live in `docs/agents/architecture.md` — to be written as the first PR.
- LLM signal decision mapping: when `decision=buy` and `intent=close_long` (or similar mismatches), current code treats them as consistent. Should be revisited under the new shape.
- Settings page exposes LLM API key — needs the same key-rotation story as exchange keys (already deferred in earlier sessions).