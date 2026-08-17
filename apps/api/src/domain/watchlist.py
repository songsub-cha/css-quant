"""Watchlist (관심/제외 목록) schema + port (SoT A5.2/C3 — domain).

``watchlist_items`` records one owner's watch-or-exclude decision on one
asset. SoT A5.2 defines the target consumers — A6.1's universe filter
(owner's exclude list applied at strategy-execution time) and A6.11's
disclosure watch (held/simulated + watch-listed assets) — but wiring an
actual caller for either is a later issue's scope (see issue #69's plan);
this module only adds the table, the port, and the DTO a
``SqlAlchemyWatchlistItemRepository.upsert`` call gets built from.

``kind`` is lowercase-valued (``watch``/``exclude``) rather than
uppercase-both-sides — same shape as ``src.domain.job_run.JobRunStatus``
(SoT B5.2/B5.3): the model's ``values_callable``, the migration's
``postgresql.ENUM`` labels, and the migration's idempotent
``DO $$ CREATE TYPE`` labels must all agree on lowercase.

Identity is ``(user_id, asset_id)`` (SoT C3's ``UNIQUE(user_id, asset_id)``)
enforced via a named unique constraint on a surrogate ``id`` primary key —
same shape as ``src.domain.password_reset.PasswordResetToken`` (surrogate
PK + a separate unique constraint), not a composite PK like
``src.domain.ai_score.AssetScore`` — a watchlist row needs its own stable
external ID (``WATCHLIST_ITEM_ID_PREFIX``) independent of its
``(user_id, asset_id)`` key.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.domain.base import Base
from src.domain.ids import generate_uuid7

WATCHLIST_ITEM_ID_PREFIX = "wl"


class WatchlistKind(StrEnum):
    WATCH = "watch"
    EXCLUDE = "exclude"


class WatchlistItemInfo(BaseModel):
    """Input DTO for one owner's watch/exclude decision on one asset.

    ``src.services.watchlist.add_or_update_item`` builds one of these after
    confirming ``asset_id`` exists, and passes it to
    ``WatchlistItemRepository.upsert``.
    """

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    asset_id: UUID
    kind: WatchlistKind
    note: str | None = None


class WatchlistItemRepository(Protocol):
    """Port ``src.services.watchlist`` depends on.

    ``SqlAlchemyWatchlistItemRepository`` implements it.
    """

    async def upsert(self, *, item: WatchlistItemInfo) -> WatchlistItem:
        """Update the ``(item.user_id, item.asset_id)`` row if one exists,
        else insert a new one — the ``UNIQUE(user_id, asset_id)`` constraint
        means re-adding the same asset switches its ``kind``/``note`` rather
        than erroring or duplicating.
        """
        ...

    async def remove(self, *, user_id: UUID, asset_id: UUID) -> None:
        """Delete the ``(user_id, asset_id)`` row if it exists — idempotent,
        no error if the row is already absent.
        """
        ...

    async def list_by_user(
        self, *, user_id: UUID, kind: WatchlistKind | None = None
    ) -> Sequence[WatchlistItem]:
        """List ``user_id``'s watchlist rows, optionally filtered to a single ``kind``."""
        ...


class WatchlistItem(Base):
    """One owner's watch/exclude decision on one asset (SoT A5.2/C3 — ``watchlist_items``)."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "asset_id", name="uq_watchlist_items_user_id_asset_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=generate_uuid7)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"))
    kind: Mapped[WatchlistKind] = mapped_column(
        SAEnum(WatchlistKind, name="watchlist_kind", values_callable=lambda e: [x.value for x in e])
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
