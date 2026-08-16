"""Redis-backed cache for LLM explanation results (SoT A6.1 5 — adapters).

Implements ``src.domain.llm_explanation.LLMExplanationCache`` structurally,
importing only ``domain`` per the layer contract ("adapters는 domain만
import") — same shape as ``src.adapters.job_lock.RedisJobLock``: takes the
``redis.asyncio.Redis`` connection directly (arq's ``ctx["redis"]`` already
provides one), no new client/pool.

Avoids repeat LLM calls for an identical structured input
(``src.domain.llm_explanation.compute_cache_key``) within the TTL window
(SoT A6.1 5 — 7 days, ``CACHE_TTL_SECONDS``).
"""

from __future__ import annotations

from redis.asyncio import Redis

from src.domain.llm_explanation import LLMExplanationResult


class RedisLLMExplanationCache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> LLMExplanationResult | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return LLMExplanationResult.model_validate_json(raw)

    async def set(self, key: str, result: LLMExplanationResult, *, ttl_seconds: int) -> None:
        await self._redis.set(key, result.model_dump_json(), ex=ttl_seconds)
