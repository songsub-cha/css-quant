"""Integration test for ``RedisJobLock`` (SoT C4).

Spins up a real Redis container and exercises ``RedisJobLock`` against it —
the ``SET NX EX`` + Lua-conditional-``DEL`` logic can't be verified against
an in-memory fake without reimplementing the exact thing under test.

Docker is unavailable in this environment and in the css-executor worktree
(``tests/conftest.py`` — "no DB container in this environment"), so the
module-scoped ``redis_client`` fixture below skips the whole module when
Docker can't be reached. Only Docker-equipped CI actually exercises the
assertions here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer

from src.adapters.job_lock import RedisJobLock


@pytest.fixture(scope="module")
def redis_client() -> Generator[Redis, None, None]:
    try:
        container = RedisContainer("redis:7-alpine")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping job lock test ({exc})")
    client = Redis(
        host=container.get_container_host_ip(), port=int(container.get_exposed_port(container.port))
    )
    try:
        yield client
    finally:
        asyncio.run(client.aclose())
        container.stop()


def test_second_acquire_fails_while_held(redis_client: Redis) -> None:
    async def _run() -> None:
        lock = RedisJobLock(redis_client)
        key = "job_lock:test-second-acquire:2026-07-29"

        token1 = await lock.acquire(key, ttl_seconds=30)
        token2 = await lock.acquire(key, ttl_seconds=30)

        assert token1 is not None
        assert token2 is None

        await lock.release(key, token1)

    asyncio.run(_run())


def test_reacquire_succeeds_after_release(redis_client: Redis) -> None:
    async def _run() -> None:
        lock = RedisJobLock(redis_client)
        key = "job_lock:test-reacquire:2026-07-29"

        token1 = await lock.acquire(key, ttl_seconds=30)
        assert token1 is not None
        await lock.release(key, token1)

        token2 = await lock.acquire(key, ttl_seconds=30)
        assert token2 is not None
        await lock.release(key, token2)

    asyncio.run(_run())


def test_release_with_wrong_token_does_not_delete(redis_client: Redis) -> None:
    async def _run() -> None:
        lock = RedisJobLock(redis_client)
        key = "job_lock:test-wrong-token:2026-07-29"

        token1 = await lock.acquire(key, ttl_seconds=30)
        assert token1 is not None

        await lock.release(key, "not-the-real-token")

        # Lock must still be held — a second acquire has to fail.
        token2 = await lock.acquire(key, ttl_seconds=30)
        assert token2 is None

        await lock.release(key, token1)

    asyncio.run(_run())
