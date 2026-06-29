"""MiniMax M3 provider — OpenAI Chat Completions compatible.

MiniMax (also branded MiniMax) hosts the M3 model at
https://api.minimaxi.com using the standard OpenAI Chat Completions
schema. Subclass OpenAIProvider with a custom base URL.
"""

from __future__ import annotations

from app.engine.openai_provider import OpenAIProvider


class MiniMaxProvider(OpenAIProvider):
    name = "minimax"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.minimaxi.com",
        timeout_seconds: float = 60.0,
        retry_policy=None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy,
        )


__all__ = ["MiniMaxProvider"]
