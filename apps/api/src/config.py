"""Application settings — leaf configuration module.

This module is intentionally **not** one of the layered packages listed in
SoT B2 (``domain``/``adapters``/``services``/``api/v1``/``engine``/``workers``).
It sits outside that dependency graph as a plain leaf: nothing in those
layers imports it, and it imports nothing from them. Only the two
composition points that are allowed to know about configuration import it
directly:

- ``src/api/deps.py`` — the DI composition point SoT B1 names explicitly
  ("DI는 `api/deps.py`").
- ``alembic/env.py`` — outside the layer graph entirely; SoT B5.5 says
  Alembic runs against ``settings.DATABASE_URL`` directly.

Because no layer imports this module, it needs no entry in the
import-linter layer contract (that contract only orders the six layers
above; a leaf that nothing in the graph depends on doesn't participate).

``adapters/db.py`` does **not** import this module — it takes a
``database_url`` string as a plain parameter, so the adapter stays
domain-only per B2 ("adapters는 domain만 import").
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ASYNCPG_DRIVER = "postgresql+asyncpg"
_PSYCOPG2_DRIVER = "postgresql+psycopg2"
_PSYCOPG_DRIVER = "postgresql+psycopg"


def normalize_database_url(value: str) -> str:
    """Rewrite any accepted Postgres URL form to the psycopg 3 driver.

    SoT B5.1 (ADR 0005): the DB driver is psycopg 3
    (``postgresql+psycopg://``); asyncpg is banned after a real SSL
    incompatibility with managed Postgres in the predecessor repo. A bare
    ``postgres://``/``postgresql://`` or an accidental ``+asyncpg``/
    ``+psycopg2`` (sync driver) in ``DATABASE_URL`` is rewritten here so a
    misconfigured env var can't silently select the wrong driver.
    """
    if value.startswith(_ASYNCPG_DRIVER):
        return _PSYCOPG_DRIVER + value[len(_ASYNCPG_DRIVER) :]
    if value.startswith(_PSYCOPG2_DRIVER):
        return _PSYCOPG_DRIVER + value[len(_PSYCOPG2_DRIVER) :]
    if value.startswith(_PSYCOPG_DRIVER):
        return value
    if value.startswith("postgresql://"):
        return _PSYCOPG_DRIVER + value[len("postgresql") :]
    if value.startswith("postgres://"):
        return _PSYCOPG_DRIVER + value[len("postgres") :]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/quantpilot"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return normalize_database_url(value)
