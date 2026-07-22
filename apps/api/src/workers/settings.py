"""Arq worker boot entrypoint (SoT D1 — worker must never be missing from compose).

Like ``alembic/env.py``, this file is a process entrypoint rather than
application logic living in the ``workers`` layer, so it is one of the few
places allowed to import ``src.config`` directly (see the docstring in
``src/config.py``). It composes ``Settings()`` the same way
``alembic/env.py`` does — no ``api/deps.get_settings`` — so no
``workers -> api`` edge is introduced (SoT B2).

No real jobs are registered yet — ``functions`` holds a single no-op
``healthcheck`` task so ``arq.worker.Worker.__init__`` (which raises
``RuntimeError`` when ``functions`` and ``cron_jobs`` are both empty) does
not reject the worker before it even gets a chance to connect to Redis.
This only proves the worker process can boot and connect to Redis; real
jobs land in Phase 2+.
"""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from src.config import Settings


def build_redis_settings(redis_url: str) -> RedisSettings:
    """Pure DSN -> RedisSettings conversion, kept separate from Settings() for testing."""
    return RedisSettings.from_dsn(redis_url)


async def healthcheck(ctx: dict[str, Any]) -> str:
    """No-op task that only exists to satisfy arq's non-empty functions requirement."""
    return "ok"


class WorkerSettings:
    functions = [healthcheck]
    redis_settings = build_redis_settings(Settings().redis_url)
