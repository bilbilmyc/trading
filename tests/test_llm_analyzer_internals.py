"""Unit tests for LLMAnalyzer internals.

Covers the helpers around the LLM call that aren't exercised by
`test_llm_analyzer_prompt*.py` (prompt format) or `test_llm_strategy.py`
(signal routing):
  - Provider selection by base_url
  - Position signature for cache fingerprinting
  - K-line summary stats
  - K-line compact encoding format
  - Response → result translation
  - Cache hit short-circuit
  - Disabled-cache behavior
  - Config defaults

The actual network call is mocked via a fake provider that returns
canned LLMResponse objects.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.engine.llm_types import (
    LLMDecided,
    LLMError,
    LLMErrorKind,
    LLMResponse,
)
from app.strategies.llm_analyzer import (
    LLMAnalyzer,
    LLMAnalyzerConfig,
    LLMAnalysisResult,
)


# ── Test doubles ──────────────────────────────────────────────────


class FakeProvider:
    """Records every call and returns canned responses.

    Supports a queue: each call pops the next response. If the queue is
    empty, returns a default 'hold' decided. Tracks call count and
    arguments for assertions.
    """

    def __init__(self, responses: Optional[List[LLMResponse]] = None) -> None:
        self.responses = list(responses or [])
        self.calls: List[Any] = []
        self._default = LLMResponse(
            decided=LLMDecided(
                decision="hold", confidence=0.0, reason="",
                model="fake", raw_response="",
            )
        )

    async def complete(self, request):
        self.calls.append(request)
        if self.responses:
            return self.responses.pop(0)
        return self._default

    async def close(self):
        pass


def _ok_response(**overrides) -> LLMResponse:
    defaults = dict(
        decision="buy", confidence=0.8, reason="looks good",
        stop_loss=49000.0, take_profit=51000.0,
        risk_level="low", risk_note="",
        model="test-model", raw_response='{"decision":"buy"}',
    )
    defaults.update(overrides)
    return LLMResponse(
        decided=LLMDecided(**defaults),
    )


def _err_response(kind: LLMErrorKind = LLMErrorKind.NETWORK, msg: str = "boom") -> LLMResponse:
    return LLMResponse(failed=LLMError(kind=kind, message=msg))


def _ticker(price: float = 50000.0) -> Dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "last_price": price,
        "price_change_pct_24h": 1.5,
        "volume_24h": 100.0,
        "quote_volume_24h": 5_000_000.0,
    }


def _klines(n: int = 30, base: float = 50000.0) -> List[Dict[str, Any]]:
    """Build a synthetic K-line series with monotonically increasing prices."""
    return [
        {
            "open_time": f"2026-01-{(i % 28) + 1:02d} 00:00",
            "open": base + i,
            "high": base + i + 50,
            "low": base + i - 50,
            "close": base + i + 10,
            "volume": 100.0,
        }
        for i in range(n)
    ]


# ── Config defaults ──────────────────────────────────────────────


def test_config_defaults() -> None:
    """Default config should be conservative and self-consistent."""
    cfg = LLMAnalyzerConfig()
    assert cfg.min_candles < cfg.max_candles
    assert 0.0 <= cfg.temperature <= 1.0
    assert cfg.default_interval == "1h"
    assert cfg.prompt_version  # non-empty version stamp


def test_config_prompt_version_bumps_cache_key() -> None:
    """Bumping prompt_version must produce a different cache fingerprint."""
    from app.engine.llm_cache import LLMFingerprintCache

    cache = LLMFingerprintCache()
    k1 = cache.fingerprint(symbol="BTCUSDT", interval="1h",
                          last_candle={"close": 50000},
                          position_signature="none", prompt_version="v2")
    k2 = cache.fingerprint(symbol="BTCUSDT", interval="1h",
                          last_candle={"close": 50000},
                          position_signature="none", prompt_version="v3")
    assert k1 != k2


# ── Provider selection by URL prefix ──────────────────────────────


def test_provider_select_deepseek_url() -> None:
    a = LLMAnalyzer(config=LLMAnalyzerConfig(
        base_url="https://api.deepseek.com/v1", api_key="k",
    ))
    assert a._provider.__class__.__name__ == "DeepSeekProvider"


def test_provider_select_minimax_url() -> None:
    a = LLMAnalyzer(config=LLMAnalyzerConfig(
        base_url="https://api.minimaxi.com/v1", api_key="k",
    ))
    assert a._provider.__class__.__name__ == "MiniMaxProvider"


def test_provider_select_anthropic_url() -> None:
    a = LLMAnalyzer(config=LLMAnalyzerConfig(
        base_url="https://api.anthropic.com", api_key="k",
    ))
    assert a._provider.__class__.__name__ == "AnthropicProvider"


def test_provider_select_ollama_localhost() -> None:
    a = LLMAnalyzer(config=LLMAnalyzerConfig(
        base_url="http://localhost:11434/v1", api_key="k",
    ))
    assert a._provider.__class__.__name__ == "OllamaProvider"


def test_provider_select_fallback_to_openai() -> None:
    """Unknown URL falls through to OpenAIProvider (most permissive)."""
    a = LLMAnalyzer(config=LLMAnalyzerConfig(
        base_url="https://api.example.com/v1", api_key="k",
    ))
    assert a._provider.__class__.__name__ == "OpenAIProvider"


# ── Position signature for cache key ──────────────────────────────


def test_position_signature_no_position() -> None:
    sig = LLMAnalyzer._position_signature(None)
    assert sig == "none"


def test_position_signature_includes_side_qty_avg() -> None:
    sig = LLMAnalyzer._position_signature({
        "side": "long", "quantity": 0.5, "avg_entry_price": 50000.0,
    })
    parts = sig.split(":")
    assert parts[0] == "long"
    assert parts[1] == "0.5"
    assert parts[2] == "50000.0"


# ── K-line summary stats ──────────────────────────────────────────


def test_kline_summary_empty() -> None:
    summary = LLMAnalyzer._kline_summary([])
    assert summary == {"count": 0}


def test_kline_summary_aggregates_correctly() -> None:
    klines = _klines(n=10, base=50000.0)
    summary = LLMAnalyzer._kline_summary(klines)
    assert summary["count"] == 10
    assert summary["first_close"] == 50000.0 + 0 + 10   # i=0 close = base+10
    assert summary["last_close"] == 50000.0 + 9 + 10  # i=9 close
    assert summary["max_high"] == 50000.0 + 9 + 50    # i=9 high
    assert summary["min_low"] == 50000.0 + 0 - 50     # i=0 low
    assert summary["atr"] > 0  # always positive for our synthetic data


def test_kline_summary_handles_single_candle() -> None:
    summary = LLMAnalyzer._kline_summary(_klines(n=1))
    assert summary["count"] == 1
    assert summary["first_close"] == summary["last_close"]


# ── K-line compact encoding format ────────────────────────────────


def test_render_klines_compact_empty() -> None:
    a = LLMAnalyzer()
    assert a._render_klines_compact([]) == ""


def test_render_klines_compact_format() -> None:
    a = LLMAnalyzer()
    klines = _klines(n=3)
    out = a._render_klines_compact(klines)

    lines = out.split("\n")
    # First line is summary header
    assert lines[0].startswith("#K n=3 ")
    assert "first=" in lines[0]
    assert "last=" in lines[0]
    assert "hi=" in lines[0]
    assert "lo=" in lines[0]
    assert "atr=" in lines[0]
    # Body has one line per candle, newest first
    assert len(lines) == 4  # header + 3 candles
    for body in lines[1:]:
        assert " o:" in body
        assert " h:" in body
        assert " l:" in body
        assert " c:" in body
        assert " v:" in body


def test_render_klines_compact_caps_at_max_rows() -> None:
    """Only `max_compact_rows` body lines should appear, even with more input."""
    a = LLMAnalyzer(config=LLMAnalyzerConfig(max_compact_rows=5))
    klines = _klines(n=20)
    out = a._render_klines_compact(klines)
    lines = out.split("\n")
    # header + 5 body lines (newest 5)
    assert len(lines) == 6


# ── Response → result translation ─────────────────────────────────


def test_translate_decided_response() -> None:
    a = LLMAnalyzer()
    response = _ok_response(decision="sell", confidence=0.7, stop_loss=48000.0)
    result = a._translate(
        response, symbol="BTCUSDT", interval="1h",
        candle_count=30, cache_hit=False,
    )
    assert isinstance(result, LLMAnalysisResult)
    assert result.decision == "sell"
    assert result.confidence == 0.7
    assert result.stop_loss == 48000.0
    assert result.take_profit == 51000.0
    assert result.analyzed_symbol == "BTCUSDT"
    assert result.analyzed_interval == "1h"
    assert result.candle_count == 30
    assert result.cache_hit is False
    assert result.error_kind is None
    assert result.model == "test-model"


def test_translate_failed_response_yields_hold() -> None:
    a = LLMAnalyzer()
    response = _err_response(kind=LLMErrorKind.NETWORK, msg="API down")
    result = a._translate(
        response, symbol="BTCUSDT", interval="1h",
        candle_count=30, cache_hit=False,
    )
    assert result.decision == "hold"
    assert result.confidence == 0.0
    assert result.error_kind == "network"
    assert "API down" in result.reason
    assert result.risk_level == "high"


def test_translate_api_key_missing_distinguishes_message() -> None:
    """API_KEY_MISSING must produce a 'not configured' risk_note, not 'API error'."""
    a = LLMAnalyzer()
    response = _err_response(kind=LLMErrorKind.API_KEY_MISSING, msg="no key")
    result = a._translate(
        response, symbol="BTCUSDT", interval="1h",
        candle_count=0, cache_hit=False,
    )
    assert result.risk_note == "未配置"
    assert result.error_kind == "api_key_missing"


# ── analyze_raw end-to-end (with mock provider) ──────────────────


@pytest.mark.asyncio
async def test_analyze_raw_calls_provider_with_full_request() -> None:
    """The provider must receive system + user messages in the right order."""
    provider = FakeProvider(responses=[_ok_response()])
    a = LLMAnalyzer(config=LLMAnalyzerConfig(api_key="k", prompt_version="v2"))
    a._provider = provider  # inject

    result = await a.analyze_raw(
        ticker=_ticker(),
        klines=_klines(30),
        symbol="BTCUSDT",
        interval="1h",
    )

    assert len(provider.calls) == 1
    req = provider.calls[0]
    # Two messages: system + user
    assert len(req.messages) == 2
    assert req.messages[0].role == "system"
    assert req.messages[1].role == "user"
    # User content must include symbol + interval + K-line summary
    assert "BTCUSDT" in req.messages[1].content
    assert "1h" in req.messages[1].content
    assert "#K" in req.messages[1].content  # compact K-line header
    # Result mirrors the response
    assert result.decision == "buy"


@pytest.mark.asyncio
async def test_analyze_raw_cache_hit_skips_provider() -> None:
    """A second call with the same fingerprint must hit the cache, not the provider."""
    provider = FakeProvider(responses=[_ok_response()])
    a = LLMAnalyzer(config=LLMAnalyzerConfig(api_key="k"))
    a._provider = provider

    # First call: provider fires, response is cached
    r1 = await a.analyze_raw(
        ticker=_ticker(), klines=_klines(30),
        symbol="BTCUSDT", interval="1h",
    )
    assert len(provider.calls) == 1
    assert r1.cache_hit is False

    # Second call: same input → must hit cache
    r2 = await a.analyze_raw(
        ticker=_ticker(), klines=_klines(30),
        symbol="BTCUSDT", interval="1h",
    )
    assert len(provider.calls) == 1  # no new call
    assert r2.cache_hit is True
    assert r2.decision == r1.decision


@pytest.mark.asyncio
async def test_analyze_raw_different_input_bypasses_cache() -> None:
    """A different last candle must produce a new provider call."""
    provider = FakeProvider(responses=[_ok_response(), _ok_response()])
    a = LLMAnalyzer(config=LLMAnalyzerConfig(api_key="k"))
    a._provider = provider

    await a.analyze_raw(
        ticker=_ticker(), klines=_klines(30),
        symbol="BTCUSDT", interval="1h",
    )
    # Move price significantly → different last candle → new cache key
    await a.analyze_raw(
        ticker=_ticker(price=60000.0), klines=_klines(30, base=60000.0),
        symbol="BTCUSDT", interval="1h",
    )
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_analyze_raw_failed_response_does_not_cache() -> None:
    """Errors must not poison the cache — a retry on same input should
    re-call the provider."""
    provider = FakeProvider(responses=[
        _err_response(kind=LLMErrorKind.NETWORK),
        _ok_response(),
    ])
    a = LLMAnalyzer(config=LLMAnalyzerConfig(api_key="k"))
    a._provider = provider

    r1 = await a.analyze_raw(
        ticker=_ticker(), klines=_klines(30),
        symbol="BTCUSDT", interval="1h",
    )
    assert r1.decision == "hold"  # degraded on error
    assert r1.error_kind == "network"

    # Retry same input — should call provider again (error wasn't cached)
    r2 = await a.analyze_raw(
        ticker=_ticker(), klines=_klines(30),
        symbol="BTCUSDT", interval="1h",
    )
    assert len(provider.calls) == 2
    assert r2.decision == "buy"  # recovery succeeded
    assert r2.cache_hit is False


# ── analyze() end-to-end with mock exchange ──────────────────────


@pytest.mark.asyncio
async def test_analyze_method_respects_min_max_candles() -> None:
    """analyze() must clamp `limit` between min_candles and max_candles."""
    provider = FakeProvider(responses=[_ok_response()])
    a = LLMAnalyzer(config=LLMAnalyzerConfig(
        api_key="k", min_candles=10, max_candles=50,
    ))
    a._provider = provider

    class FakeExchange:
        async def get_ticker(self, symbol):
            return _ticker()
        async def get_klines(self, symbol, interval, limit):
            return _klines(n=limit)

    # limit=2 → clamped up to min=10
    await a.analyze(FakeExchange(), "BTCUSDT", interval="1h", limit=2)
    assert provider.calls[0].messages[1].content.count(" o:") == 10

    # limit=999 → clamped down to max=50
    provider.calls.clear()
    await a.analyze(FakeExchange(), "BTCUSDT", interval="1h", limit=999)
    # The K-line body caps at max_compact_rows (default 30)
    # so the rendered count is at most min(max_compact_rows, max_candles) = 30
    assert provider.calls[0].messages[1].content.count(" o:") <= 30
