"""Watchlist add/remove/list orchestration (SoT A5.2 — services layer).

Thin service between ``api/v1/watchlist.py`` and the
``WatchlistItemRepository``/``AssetRepository`` ports. ``add_or_update_item``
confirms ``asset_id`` refers to a real asset (``AssetRepository.list_by_ids``,
the same bulk lookup ``list_ranked_scores`` uses) before delegating to the
repository's upsert, so a bad ``asset_id`` fails with 404 rather than an FK
``IntegrityError`` surfacing as an unhandled 500. ``list_items`` uses the same
bulk lookup to pair each row with its ``Asset`` so the API layer can render
ticker/name instead of a raw ``asset_id`` (same shape as
``list_ranked_scores``); a row whose asset can't be found is skipped rather
than erroring, since asset deletion isn't a real path in this codebase but a
future-proof no-op is cheap here.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from src.domain.asset import Asset, AssetRepository
from src.domain.watchlist import (
    WatchlistItem,
    WatchlistItemInfo,
    WatchlistItemRepository,
    WatchlistKind,
)
from src.errors import ApiError, ErrorCode


async def add_or_update_item(
    watchlist_repo: WatchlistItemRepository,
    asset_repo: AssetRepository,
    *,
    user_id: UUID,
    asset_id: UUID,
    kind: WatchlistKind,
    note: str | None,
) -> WatchlistItem:
    assets = await asset_repo.list_by_ids([asset_id])
    if not assets:
        raise ApiError(status=404, code=ErrorCode.ASSET_NOT_FOUND, detail="Asset not found.")
    return await watchlist_repo.upsert(
        item=WatchlistItemInfo(user_id=user_id, asset_id=asset_id, kind=kind, note=note)
    )


async def remove_item(
    watchlist_repo: WatchlistItemRepository, *, user_id: UUID, asset_id: UUID
) -> None:
    await watchlist_repo.remove(user_id=user_id, asset_id=asset_id)


async def list_items(
    watchlist_repo: WatchlistItemRepository,
    asset_repo: AssetRepository,
    *,
    user_id: UUID,
    kind: WatchlistKind | None,
) -> Sequence[tuple[WatchlistItem, Asset]]:
    items = await watchlist_repo.list_by_user(user_id=user_id, kind=kind)
    if not items:
        return []

    assets = await asset_repo.list_by_ids([item.asset_id for item in items])
    assets_by_id = {asset.id: asset for asset in assets}

    return [
        (item, assets_by_id[item.asset_id]) for item in items if item.asset_id in assets_by_id
    ]
