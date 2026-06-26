"""Tests for LLMFingerprintCache."""

from __future__ import annotations

import time

import pytest

from app.engine.llm_cache import LLMFingerprintCache
from app.engine.llm_types import LLMDecided, LLMResponse


def _ok(decision: str = "buy") -> LLMResponse:
    return LLMResponse(
        decided=LLMDecided(decision=decision, confidence=0.7, reason="ok"),
        prompt_tokens=12,
        completion_tokens=34,
    )


def test_fingerprint_is_stable_across_calls() -> None:
    fp1 = LLMFingerprintCache.fingerprint("BTCUSDT", "1h", {"close": 100.0}, "long:0.001", "v1")
    fp2 = LLMFingerprintCache.fingerprint("BTCUSDT", "1h", {"close": 100.0}, "long:0.001", "v1")
    assert fp1 == fp2


def test_fingerprint_changes_when_input_changes() -> None:
    fp1 = LLMFingerprintCache.fingerprint("BTCUSDT", "1h", {"close": 100.0}, "long:0.001", "v1")
    fp2 = LLMFingerprintCache.fingerprint("BTCUSDT", "1h", {"close": 100.5}, "long:0.001", "v1")
    assert fp1 != fp2


def test_miss_then_hit() -> None:
    cache = LLMFingerprintCache(ttl_seconds=10.0)
    assert cache.get("k1") is None
    cache.put("k1", _ok())
    hit = cache.get("k1")
    assert hit is not None
    assert hit.decided.decision == "buy"


def test_expired_entry_is_miss() -> None:
    cache = LLMFingerprintCache(ttl_seconds=0.05)
    cache.put("k", _ok())
    time.sleep(0.1)
    assert cache.get("k") is None


def test_failure_responses_are_not_cached() -> None:
    from app.engine.llm_types import LLMError, LLMErrorKind

    cache = LLMFingerprintCache()
    failed = LLMResponse(failed=LLMError(kind=LLMErrorKind.TIMEOUT, message="x", retryable=True))
    cache.put("k", failed)
    assert cache.get("k") is None


def test_stats_track_hits_and_misses() -> None:
    cache = LLMFingerprintCache(ttl_seconds=10.0)
    cache.put("a", _ok())
    cache.get("a")  # hit
    cache.get("b")  # miss
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_eviction_drops_oldest_when_full() -> None:
    cache = LLMFingerprintCache(max_entries=2)
    cache.put("a", _ok("buy"))
    cache.put("b", _ok("sell"))
    cache.put("c", _ok("hold"))  # evicts "a"
    assert cache.get("a") is None
    assert cache.get("b") is not None
    assert cache.get("c") is not None