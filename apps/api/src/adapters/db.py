"""SQLAlchemy async engine factory (SoT B2 — adapters layer, domain-only).

Takes the connection URL as a plain parameter rather than importing
``src.config`` — adapters may only import ``domain`` (SoT B2). Composition
with ``Settings`` happens at the DI layer (``src/api/deps.py``) and, outside
the layer graph, in ``alembic/env.py`` (SoT B5.5), both of which call
``get_engine()`` so there is a single engine-construction code path.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import Pool


def get_engine(database_url: str, *, poolclass: type[Pool] | None = None) -> AsyncEngine:
    kwargs = {} if poolclass is None else {"poolclass": poolclass}
    return create_async_engine(database_url, **kwargs)
