"""POST/GET/DELETE /api/v1/watchlist — watchlist CRUD endpoints (SoT A5.2, thin router).

``router -> service -> adapter/domain`` (SoT B2, same shape as
``api/v1/scores.py``): all asset-existence checking and repository
delegation happens in ``src.services.watchlist``; this module only wires
the request, requires auth (owner-scoped data, same principle as every
other protected endpoint), and shapes the response.

``GET`` returns an unwrapped array (SoT B4.4's default rule) rather than a
``{"items": [...]}`` wrapper — unlike ``scores.py``'s
``ScoreRankingResponse``, there is no required top-level metadata
(``score_date``) that would justify the wrapper exception.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, field_validator

from src.api.deps import get_asset_repository, get_current_user, get_watchlist_item_repository
from src.domain.asset import ASSET_ID_PREFIX, AssetRepository
from src.domain.ids import format_prefixed_id, parse_prefixed_id
from src.domain.user import User
from src.domain.watchlist import (
    WATCHLIST_ITEM_ID_PREFIX,
    WatchlistItem,
    WatchlistItemRepository,
    WatchlistKind,
)
from src.services.watchlist import add_or_update_item, list_items, remove_item

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


class WatchlistItemRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: str
    kind: WatchlistKind
    note: str | None = None

    @field_validator("asset_id")
    @classmethod
    def _validate_asset_id_format(cls, value: str) -> str:
        # Raises ValueError on a missing/mismatched prefix or malformed UUID
        # tail; Pydantic turns that into a 422 (SoT B4.4).
        parse_prefixed_id(ASSET_ID_PREFIX, value)
        return value


class WatchlistItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    asset_id: str
    kind: WatchlistKind
    note: str | None
    created_at: datetime

    @classmethod
    def from_item(cls, item: WatchlistItem) -> WatchlistItemResponse:
        return cls(
            id=format_prefixed_id(WATCHLIST_ITEM_ID_PREFIX, item.id),
            asset_id=format_prefixed_id(ASSET_ID_PREFIX, item.asset_id),
            kind=item.kind,
            note=item.note,
            created_at=item.created_at,
        )


def _parsed_path_asset_id(asset_id: str) -> UUID:
    try:
        return parse_prefixed_id(ASSET_ID_PREFIX, asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("")
async def add_watchlist_item(
    request: WatchlistItemRequest,
    watchlist_repo: Annotated[WatchlistItemRepository, Depends(get_watchlist_item_repository)],
    asset_repo: Annotated[AssetRepository, Depends(get_asset_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WatchlistItemResponse:
    item = await add_or_update_item(
        watchlist_repo,
        asset_repo,
        user_id=current_user.id,
        asset_id=parse_prefixed_id(ASSET_ID_PREFIX, request.asset_id),
        kind=request.kind,
        note=request.note,
    )
    return WatchlistItemResponse.from_item(item)


@router.get("")
async def list_watchlist_items(
    watchlist_repo: Annotated[WatchlistItemRepository, Depends(get_watchlist_item_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
    kind: Annotated[WatchlistKind | None, Query()] = None,
) -> list[WatchlistItemResponse]:
    items = await list_items(watchlist_repo, user_id=current_user.id, kind=kind)
    return [WatchlistItemResponse.from_item(item) for item in items]


@router.delete("/{asset_id}", status_code=204)
async def delete_watchlist_item(
    current_user: Annotated[User, Depends(get_current_user)],
    asset_id: Annotated[UUID, Depends(_parsed_path_asset_id)],
    watchlist_repo: Annotated[WatchlistItemRepository, Depends(get_watchlist_item_repository)],
) -> Response:
    await remove_item(watchlist_repo, user_id=current_user.id, asset_id=asset_id)
    return Response(status_code=204)
