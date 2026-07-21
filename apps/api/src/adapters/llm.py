"""LLM adapter port + fake-by-default implementation.

SoT ADR 0004 (fake-by-default adapters) / B3: every external integration sits
behind a Protocol with a deterministic fake as the default implementation, so
the whole app runs with zero API keys. Real providers (``OpenAILLMClient``,
``AnthropicLLMClient``) are added in a later issue behind the same interface.
"""

from __future__ import annotations

import hashlib
from typing import Protocol


class LLMClient(Protocol):
    """Port for LLM text completion, selected via the ``LLM_ADAPTER`` env var."""

    async def complete(self, prompt: str) -> str: ...


class FakeLLMClient:
    """Deterministic stand-in for a real LLM provider.

    Never calls out to the network. The same prompt always yields the same
    output, which keeps tests and local runs reproducible without secrets.
    """

    async def complete(self, prompt: str) -> str:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        return f"[fake-llm:{digest}] {prompt}"
