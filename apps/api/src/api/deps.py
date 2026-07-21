"""DI composition point (SoT B1/B2 — "DI는 `api/deps.py`").

This is one of the two places allowed to import ``src.config`` directly
(the other is ``alembic/env.py``, which sits outside the layer graph). No
routers exist yet that need the engine; ``get_db_engine`` is provided now so
future services/routers have a single place to assemble it.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine

from src.adapters.db import get_engine
from src.config import Settings


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_db_engine() -> AsyncEngine:
    return get_engine(get_settings().database_url)
