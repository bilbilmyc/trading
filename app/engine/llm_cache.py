"""Fingerprint cache for LLM responses.

Key = sha256(symbol + interval + last_candle_hash + position_signature + prompt_version).
Hit returns cached Decided; miss computes fresh.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.engine.llm_types import LLMDecided, LLMResponse


@dataclass(frozen=True)
class _Entry:
    decided: LLMDecided
    expires_at: float
    prompt_tokens: int
    completion_tokens: int


class LLMFingerprintCache:
    def __init__(self, ttl_seconds: float = 30.0, max_entries: int = 1024) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._store: Dict[str, _Entry] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def fingerprint(
        symbol: str,
        interval: str,
        last_candle: Dict[str, Any],
        position_signature: str,
        prompt_version: str,
    ) -> str:
        payload = {
            "symbol": symbol,
            "interval": interval,
            "candle": last_candle,
            "pos": position_signature,
            "v": prompt_version,
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[LLMResponse]:
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        if entry.expires_at < time.monotonic():
            del self._store[key]
            self.misses += 1
            return None
        self.hits += 1
        return LLMResponse(
            decided=entry.decided,
            prompt_tokens=entry.prompt_tokens,
            completion_tokens=entry.completion_tokens,
        )

    def put(self, key: str, response: LLMResponse) -> None:
        if response.decided is None:
            return  # don't cache failures
        if len(self._store) >= self._max:
            # Drop oldest by insertion order (dicts preserve insertion order in 3.7+)
            oldest = next(iter(self._store))
            del self._store[oldest]
        self._store[key] = _Entry(
            decided=response.decided,
            expires_at=time.monotonic() + self._ttl,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": (self.hits / total) if total else 0.0,
            "size": len(self._store),
        }


__all__ = ["LLMFingerprintCache"]