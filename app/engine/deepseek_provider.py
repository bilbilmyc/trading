"""DeepSeek v4 provider — OpenAI Chat Completions compatible.

DeepSeek's API is at https://api.deepseek.com (also supports /v1
prefix) and uses the standard OpenAI Chat Completions schema. We
subclass OpenAIProvider and only override the default base URL.
"""

from __future__ import annotations

from app.engine.openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 60.0,
        retry_policy=None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy,
        )


__all__ = ["DeepSeekProvider"]
