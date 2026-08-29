"""Strategy schema + port (SoT A5.3/A6.5/C3 — domain).

``strategies`` is one owner's trading rule set — the input Phase 5
(backtest), Phase 6 (paper trading), and Phase 7 (risk engine) all consume.
This module only adds the table, the port, and the DTO
``SqlAlchemyStrategyRepository.create`` builds from; wiring an actual
execution consumer is later Phase scope (see issue #75's plan). Replicates
``src.domain.watchlist``'s 4-layer shape (issue #69/#70 precedent).

**Two interpretation decisions** (SoT prose does not state either
explicitly — fixed here per issue #75's plan):

1. ``execution_mode`` is a dedicated ``strategies`` table column, not a
   field inside ``config`` jsonb, even though SoT A6.5 lists it as the last
   item of the config schema. SoT C3 already defines
   ``strategies.execution_mode`` as its own column alongside ``status``/
   ``version`` — mirroring that (rather than the A6.5 prose list) avoids
   duplicating the same fact in two places with no single source of truth.
2. ``GET /api/v1/strategies`` returns an unwrapped array, no cursor
   pagination — same reasoning as ``watchlist_items`` (SoT B4.4's cursor
   rule is a default, not a mandate; a single owner's strategy list has no
   scale pressure toward pagination).

``status``/``execution_mode`` are lowercase-valued StrEnums (SoT B5.2/B5.3):
the model's ``values_callable``, the migration's ``postgresql.ENUM``
labels, and the migration's idempotent ``DO $$ CREATE TYPE`` labels must
all agree on lowercase — same trap ``watchlist_kind``/``job_run_status``
already navigate.

``deleted_at`` implements SoT B4.10's "전략은 soft delete" — a strategy is
never hard-deleted; ``StrategyRepository.get_by_id``/``list_by_user`` both
filter it out so a soft-deleted row behaves as 404/absent everywhere a
caller can observe it (same shape as absent-vs-other-owner, matching
``services.strategy.STRATEGY_NOT_FOUND``'s "don't leak existence" goal).

``get_by_id`` is scoped to ``(user_id, strategy_id)`` in one query — an
IDOR guard at the query level, not a fetch-then-compare-owner check (same
pattern as ``watchlist``'s ``list_by_user``, generalized to a by-id lookup
here since strategies, unlike watchlist rows, are addressed individually).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base
from src.domain.ids import generate_uuid7

STRATEGY_ID_PREFIX = "str"


class StrategyStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ExecutionMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE_APPROVAL = "live_approval"
    LIVE_AUTO = "live_auto"


class StrategyInfo(BaseModel):
    """Input DTO for creating a strategy.

    ``src.services.strategy.create_strategy`` builds one of these and passes
    it to ``StrategyRepository.create``, which always fixes
    ``status=draft, version=1`` regardless of what the caller supplies here
    (matching SoT A5.3 — a strategy always starts as a draft).
    """

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    name: str
    description: str | None
    execution_mode: ExecutionMode
    config: dict[str, Any]


class StrategyRepository(Protocol):
    """Port ``src.services.strategy`` depends on; ``SqlAlchemyStrategyRepository`` implements it."""

    async def create(self, *, info: StrategyInfo) -> Strategy:
        """Insert a new ``status=draft, version=1`` row."""
        ...

    async def get_by_id(self, *, user_id: UUID, strategy_id: UUID) -> Strategy | None:
        """Look up a non-deleted row scoped to ``user_id`` — IDOR-safe at the query level."""
        ...

    async def list_by_user(
        self, *, user_id: UUID, status: StrategyStatus | None = None
    ) -> Sequence[Strategy]:
        """List ``user_id``'s non-deleted strategies, optionally filtered to one ``status``."""
        ...

    async def update(self, strategy: Strategy) -> Strategy:
        """Persist in-place mutations already applied to a fetched ``strategy``."""
        ...

    async def soft_delete(self, strategy: Strategy) -> None:
        """Set ``deleted_at`` on an already-fetched ``strategy``."""
        ...


class Strategy(Base):
    """One owner's trading rule set (SoT A5.3/C3 — ``strategies``)."""

    __tablename__ = "strategies"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=generate_uuid7)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[StrategyStatus] = mapped_column(
        SAEnum(
            StrategyStatus, name="strategy_status", values_callable=lambda e: [x.value for x in e]
        )
    )
    execution_mode: Mapped[ExecutionMode] = mapped_column(
        SAEnum(
            ExecutionMode,
            name="strategy_execution_mode",
            values_callable=lambda e: [x.value for x in e],
        )
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
