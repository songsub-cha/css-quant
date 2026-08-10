"""Redis-backed distributed lock preventing concurrent job runs (SoT C4 — adapters).

Implements ``src.domain.job_run.JobLock`` structurally, importing only
``domain`` per the layer contract ("adapters는 domain만 import"). Takes the
``redis.asyncio.Redis`` connection arq's task ``ctx["redis"]`` already
provides (``arq.connections.ArqRedis`` is a subclass), so no new client/pool
and no new package dependency is introduced.
"""

from __future__ import annotations

import secrets

from redis.asyncio import Redis

# Only delete the key if it still holds the caller's own token — otherwise a
# slow holder could delete a lock another process already re-acquired after
# TTL expiry (the classic "release wrong holder's lock" bug).
_RELEASE_IF_OWNER = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


class RedisJobLock:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def acquire(self, key: str, *, ttl_seconds: int) -> str | None:
        token = secrets.token_hex(16)
        acquired = await self._redis.set(key, token, nx=True, ex=ttl_seconds)
        return token if acquired else None

    async def release(self, key: str, token: str) -> None:
        # redis-py's stub types Redis.eval as returning `Awaitable[str] | str`
        # (shared across the sync/async clients); on this async client it is
        # always awaitable at runtime.
        await self._redis.eval(_RELEASE_IF_OWNER, 1, key, token)  # type: ignore[misc]
