"""Arq worker boot entrypoint (SoT D1 — worker must never be missing from compose).

Like ``alembic/env.py``, this file is a process entrypoint rather than
application logic living in the ``workers`` layer, so it is one of the few
places allowed to import ``src.config`` directly (see the docstring in
``src/config.py``). It composes ``Settings()`` the same way
``alembic/env.py`` does — no ``api/deps.get_settings`` — so no
``workers -> api`` edge is introduced (SoT B2).

No jobs are registered yet (``functions=[]``); this only proves the worker
process can boot and connect to Redis. Real jobs land in Phase 2+.
"""

from __future__ import annotations

from arq.connections import RedisSettings

from src.config import Settings


def build_redis_settings(redis_url: str) -> RedisSettings:
    """Pure DSN -> RedisSettings conversion, kept separate from Settings() for testing."""
    return RedisSettings.from_dsn(redis_url)


class WorkerSettings:
    functions: list = []
    redis_settings = build_redis_settings(Settings().redis_url)
