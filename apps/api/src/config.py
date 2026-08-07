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
- ``src/workers/settings.py`` and ``src/workers/backfill_cli.py`` **only** —
  not the rest of ``src/workers/*``. ``workers`` is one of the six layers SoT
  B2 orders, so a task module reaching into this file for config would be an
  ordinary layer violation. But both of these are process entrypoints
  (``WorkerSettings`` is the Arq process's boot entrypoint;
  ``backfill_cli.py`` is a one-off script invoked directly, never scheduled),
  the same role ``alembic/env.py`` plays for migrations, not application
  logic living in the ``workers`` layer — so each composes ``Settings`` the
  same way ``alembic/env.py`` does, without routing through
  ``api/deps.get_settings`` (which would create a ``workers -> api`` edge —
  the reverse of the ``api -> ... -> workers`` direction SoT B2 allows).

Because no layer imports this module, it needs no entry in the
import-linter layer contract (that contract only orders the six layers
above; a leaf that nothing in the graph depends on doesn't participate).

``adapters/db.py`` does **not** import this module — it takes a
``database_url`` string as a plain parameter, so the adapter stays
domain-only per B2 ("adapters는 domain만 import").
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator
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
    redis_url: str = "redis://localhost:6379/0"

    # SoT B4.6 / D2: dedicated env var for cookie Secure, never derived from
    # ENVIRONMENT — the predecessor repo's trap was "production" + HTTP-only
    # IP access locking the owner out of login. No default on purpose: every
    # deployment (Tailscale HTTPS vs. LAN HTTP fallback, SoT D3) must set
    # this explicitly rather than inherit a guessed value.
    cookie_secure: bool
    # SoT D2: signup is disabled by default; flipped true only for the
    # one-time owner bootstrap, then back to false.
    signup_enabled: bool = False

    # SoT D2/B4.6: JWT signing key. No default (same rationale as
    # cookie_secure) — but unlike a bool, a `str` field accepts an *empty*
    # string as a "valid" value with no coercion to fail on. A bare
    # `SECRET_KEY=` line in .env (e.g. from `cp .env.example .env` before
    # filling in a real value) would otherwise load successfully and the
    # app would sign JWTs with an empty key — fail-open. `min_length=32`
    # makes empty (and any too-short) values raise ValidationError too, so
    # this field fails closed the same way cookie_secure's bool coercion
    # does (SoT 원칙 8).
    secret_key: str = Field(min_length=32)

    # SoT B3: fake-by-default adapter swap. "fake" keeps the whole app
    # running with zero network access/API keys; "krx" selects the real
    # pykrx-backed adapters (src/adapters/data_sources.py), wired in
    # src/workers/settings.py.
    data_source: Literal["fake", "krx"] = "fake"

    # SoT C1/D2: DART OpenAPI key for the real financial-statement adapter
    # (src/adapters/dart_financial_data_source.py). Optional — unlike
    # secret_key, "fake" mode must run with no key set at all, so this has
    # no min_length floor; src/workers/settings.py is what fails closed when
    # DATA_SOURCE=krx and this is left empty.
    dart_api_key: str | None = None

    # SoT A6.1: universe filter thresholds (src.workers.universe_filter is
    # the only caller) — env-var-configurable so these never get hardcoded
    # as magic numbers in engine/worker code.
    universe_market_cap_min: Decimal = Decimal("300000000000")  # 시총 3,000억
    universe_avg_trading_value_min: Decimal = Decimal("1000000000")  # 20일 평균 거래대금 10억
    universe_min_listed_days: int = 60  # 상장 60일 이상

    # SoT A6.4: data quality gate thresholds (src.workers.quality_gate is the
    # only caller) — env-var-configurable, never hardcoded.
    quality_gate_coverage_min_pct: Decimal = Decimal("0.98")  # 커버리지 98% 이상
    quality_gate_max_price_move_pct: Decimal = Decimal("0.30")  # 등락률 ±30% 이내

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return normalize_database_url(value)
