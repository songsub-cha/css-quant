"""POST/GET/PATCH/DELETE + action endpoints /api/v1/strategies (SoT A5.3, thin router).

``router -> service -> adapter/domain`` (SoT B2, same shape as
``api/v1/watchlist.py``): all state-transition/version-bump logic lives in
``src.services.strategy``; this module only wires the request, requires
auth (owner-scoped data), and shapes the response.

``GET /templates`` is registered **before** ``GET /{strategy_id}`` —
FastAPI/Starlette matches routes in registration order, so if the dynamic
route came first, a request for ``/templates`` would match
``{strategy_id}="templates"`` instead of the static route. This ordering is
the regression guard, not a comment alone — ``test_strategy_api.py`` also
asserts the two don't collide.

``GET`` list returns an unwrapped array (SoT B4.4's default rule), same
reasoning as ``watchlist.py``'s docstring.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from src.api.deps import get_current_user, get_strategy_repository
from src.domain.ids import format_prefixed_id, parse_prefixed_id
from src.domain.strategy import (
    STRATEGY_ID_PREFIX,
    ExecutionMode,
    Strategy,
    StrategyRepository,
    StrategyStatus,
)
from src.domain.strategy_config import StrategyConfig
from src.domain.strategy_template import StrategyTemplate
from src.domain.user import User
from src.services.strategy import (
    activate_strategy,
    archive_strategy,
    clone_strategy,
    create_strategy,
    delete_strategy,
    get_strategy,
    list_strategies,
    list_templates,
    pause_strategy,
    update_strategy,
)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


class StrategyCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    execution_mode: ExecutionMode
    config: StrategyConfig = Field(default_factory=StrategyConfig)


class StrategyUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str | None = None
    description: str | None = None
    execution_mode: ExecutionMode | None = None
    config: StrategyConfig | None = None


class StrategyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str | None
    status: StrategyStatus
    execution_mode: ExecutionMode
    config: StrategyConfig
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_strategy(cls, strategy: Strategy) -> StrategyResponse:
        return cls(
            id=format_prefixed_id(STRATEGY_ID_PREFIX, strategy.id),
            name=strategy.name,
            description=strategy.description,
            status=strategy.status,
            execution_mode=strategy.execution_mode,
            config=StrategyConfig.model_validate(strategy.config),
            version=strategy.version,
            created_at=strategy.created_at,
            updated_at=strategy.updated_at,
        )


class StrategyTemplateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    description: str
    config: StrategyConfig

    @classmethod
    def from_template(cls, template: StrategyTemplate) -> StrategyTemplateResponse:
        return cls(
            key=template.key,
            name=template.name,
            description=template.description,
            config=template.config,
        )


def _parsed_path_strategy_id(strategy_id: str) -> UUID:
    try:
        return parse_prefixed_id(STRATEGY_ID_PREFIX, strategy_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("")
async def create_strategy_endpoint(
    request: StrategyCreateRequest,
    repo: Annotated[StrategyRepository, Depends(get_strategy_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyResponse:
    strategy = await create_strategy(
        repo,
        user_id=current_user.id,
        name=request.name,
        description=request.description,
        execution_mode=request.execution_mode,
        config=request.config.model_dump(mode="json"),
    )
    return StrategyResponse.from_strategy(strategy)


@router.get("")
async def list_strategies_endpoint(
    repo: Annotated[StrategyRepository, Depends(get_strategy_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
    status: Annotated[StrategyStatus | None, Query()] = None,
) -> list[StrategyResponse]:
    strategies = await list_strategies(repo, user_id=current_user.id, status=status)
    return [StrategyResponse.from_strategy(s) for s in strategies]


@router.get("/templates")
async def list_strategy_templates_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[StrategyTemplateResponse]:
    return [StrategyTemplateResponse.from_template(t) for t in list_templates()]


@router.get("/{strategy_id}")
async def get_strategy_endpoint(
    strategy_id: Annotated[UUID, Depends(_parsed_path_strategy_id)],
    repo: Annotated[StrategyRepository, Depends(get_strategy_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyResponse:
    strategy = await get_strategy(repo, user_id=current_user.id, strategy_id=strategy_id)
    return StrategyResponse.from_strategy(strategy)


@router.patch("/{strategy_id}")
async def update_strategy_endpoint(
    strategy_id: Annotated[UUID, Depends(_parsed_path_strategy_id)],
    request: StrategyUpdateRequest,
    repo: Annotated[StrategyRepository, Depends(get_strategy_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyResponse:
    strategy = await update_strategy(
        repo,
        user_id=current_user.id,
        strategy_id=strategy_id,
        name=request.name,
        description=request.description,
        execution_mode=request.execution_mode,
        config=request.config.model_dump(mode="json") if request.config is not None else None,
    )
    return StrategyResponse.from_strategy(strategy)


@router.post("/{strategy_id}/activate")
async def activate_strategy_endpoint(
    strategy_id: Annotated[UUID, Depends(_parsed_path_strategy_id)],
    repo: Annotated[StrategyRepository, Depends(get_strategy_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyResponse:
    strategy = await activate_strategy(repo, user_id=current_user.id, strategy_id=strategy_id)
    return StrategyResponse.from_strategy(strategy)


@router.post("/{strategy_id}/pause")
async def pause_strategy_endpoint(
    strategy_id: Annotated[UUID, Depends(_parsed_path_strategy_id)],
    repo: Annotated[StrategyRepository, Depends(get_strategy_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyResponse:
    strategy = await pause_strategy(repo, user_id=current_user.id, strategy_id=strategy_id)
    return StrategyResponse.from_strategy(strategy)


@router.post("/{strategy_id}/archive")
async def archive_strategy_endpoint(
    strategy_id: Annotated[UUID, Depends(_parsed_path_strategy_id)],
    repo: Annotated[StrategyRepository, Depends(get_strategy_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyResponse:
    strategy = await archive_strategy(repo, user_id=current_user.id, strategy_id=strategy_id)
    return StrategyResponse.from_strategy(strategy)


@router.post("/{strategy_id}/clone")
async def clone_strategy_endpoint(
    strategy_id: Annotated[UUID, Depends(_parsed_path_strategy_id)],
    repo: Annotated[StrategyRepository, Depends(get_strategy_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StrategyResponse:
    strategy = await clone_strategy(repo, user_id=current_user.id, strategy_id=strategy_id)
    return StrategyResponse.from_strategy(strategy)


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy_endpoint(
    strategy_id: Annotated[UUID, Depends(_parsed_path_strategy_id)],
    repo: Annotated[StrategyRepository, Depends(get_strategy_repository)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    await delete_strategy(repo, user_id=current_user.id, strategy_id=strategy_id)
    return Response(status_code=204)
