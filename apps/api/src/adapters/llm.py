"""LLM adapter port + fake-by-default implementation.

SoT ADR 0004 (fake-by-default adapters) / B3: every external integration sits
behind a Protocol with a deterministic fake as the default implementation, so
the whole app runs with zero API keys. Real providers (``OpenAILLMClient``,
``AnthropicLLMClient`` — real function calling, Batch API, prompt caching,
per-call token/cost accounting) are added in a later issue behind the same
``complete(prompt) -> str`` interface; this issue (#64) only approximates
structured output by asking for JSON-as-text in the prompt (see
``src.domain.llm_explanation.build_explanation_prompt``) and parsing the
response back (``validate_explanation_output``) — the signature below is
otherwise unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol


class LLMClient(Protocol):
    """Port for LLM text completion, selected via the ``LLM_ADAPTER`` env var."""

    async def complete(self, prompt: str) -> str: ...


class FakeLLMClient:
    """Deterministic stand-in for a real LLM provider.

    Never calls out to the network. The same prompt always yields the same
    output, which keeps tests and local runs reproducible without secrets.
    Returns a JSON object matching ``src.domain.llm_explanation``'s expected
    schema (``summary``/``positive_reasons``/``risk_reasons``) so the whole
    stage-5 pipeline (``src.workers.llm_explanation``) round-trips against
    this fake without a real vendor key.
    """

    async def complete(self, prompt: str) -> str:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        return json.dumps(
            {
                "summary": f"최근 지표 변화가 관측되었습니다 (참조 {digest}).",
                "positive_reasons": [f"양호한 흐름 신호가 있습니다 (참조 {digest})."],
                "risk_reasons": [f"주의가 필요한 신호가 있습니다 (참조 {digest})."],
            },
            ensure_ascii=False,
        )
