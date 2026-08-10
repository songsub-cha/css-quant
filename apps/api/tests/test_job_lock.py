"""Integration test for ``RedisJobLock`` (SoT C4).

Spins up a real Redis container and exercises ``RedisJobLock`` against it —
the ``SET NX EX`` + Lua-conditional-``DEL`` logic can't be verified against
an in-memory fake without reimplementing the exact thing under test.

Docker is unavailable in this environment and in the css-executor worktree
(``tests/conftest.py`` — "no DB container in this environment"), so the
module-scoped ``redis_container`` fixture below skips the whole module when
Docker can't be reached. Only Docker-equipped CI actually exercises the
assertions here.

Each test builds and tears down its own ``Redis`` client inside its own
``asyncio.run(_run())`` call (same "no pytest-asyncio dependency" pattern as
``test_job_run_service.py``/``test_asset_sync.py``) rather than sharing one
client across tests via a fixture. ``redis.asyncio.Redis`` binds its
connections to whichever event loop is running when they're first used;
``asyncio.run`` opens and closes a *new* loop per test, so a client built
once (e.g. in a module-scoped fixture) and reused across tests ends up with
connections attached to a loop that a later test already closed — surfacing
as ``RuntimeError: Event loop is closed`` / "attached to a different loop".
Only the container itself (a synchronous Docker resource, not
event-loop-bound) is safe to share module-wide.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer

from src.adapters.job_lock import RedisJobLock


@pytest.fixture(scope="module")
def redis_container() -> Generator[RedisContainer, None, None]:
    try:
        container = RedisContainer("redis:7-alpine")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping job lock test ({exc})")
    try:
        yield container
    finally:
        container.stop()


def test_second_acquire_fails_while_held(redis_container: RedisContainer) -> None:
    async def _run() -> None:
        client = Redis(
            host=redis_container.get_container_host_ip(),
            port=int(redis_container.get_exposed_port(redis_container.port)),
        )
        try:
            lock = RedisJobLock(client)
            key = "job_lock:test-second-acquire:2026-07-29"

            token1 = await lock.acquire(key, ttl_seconds=30)
            token2 = await lock.acquire(key, ttl_seconds=30)

            assert token1 is not None
            assert token2 is None

            await lock.release(key, token1)
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_reacquire_succeeds_after_release(redis_container: RedisContainer) -> None:
    async def _run() -> None:
        client = Redis(
            host=redis_container.get_container_host_ip(),
            port=int(redis_container.get_exposed_port(redis_container.port)),
        )
        try:
            lock = RedisJobLock(client)
            key = "job_lock:test-reacquire:2026-07-29"

            token1 = await lock.acquire(key, ttl_seconds=30)
            assert token1 is not None
            await lock.release(key, token1)

            token2 = await lock.acquire(key, ttl_seconds=30)
            assert token2 is not None
            await lock.release(key, token2)
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_release_with_wrong_token_does_not_delete(redis_container: RedisContainer) -> None:
    async def _run() -> None:
        client = Redis(
            host=redis_container.get_container_host_ip(),
            port=int(redis_container.get_exposed_port(redis_container.port)),
        )
        try:
            lock = RedisJobLock(client)
            key = "job_lock:test-wrong-token:2026-07-29"

            token1 = await lock.acquire(key, ttl_seconds=30)
            assert token1 is not None

            await lock.release(key, "not-the-real-token")

            # Lock must still be held — a second acquire has to fail.
            token2 = await lock.acquire(key, ttl_seconds=30)
            assert token2 is None

            await lock.release(key, token1)
        finally:
            await client.aclose()

    asyncio.run(_run())
