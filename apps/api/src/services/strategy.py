"""Strategy CRUD + state-transition orchestration (SoT A5.3/A6.5 — services layer).

Thin service between ``api/v1/strategies.py`` and ``StrategyRepository`` —
same shape as ``src.services.watchlist``. ``config`` validation itself
happens at the API boundary (``StrategyConfig`` Pydantic parsing, SoT A5.3
"저장 전 검증") before it ever reaches this module; every function here
receives an already-validated ``dict[str, Any]``.

**State transition table** (SoT A5.3's 복제/일시정지/보관, resolved into an
explicit table by issue #75's plan — SoT prose doesn't spell out the graph):
``draft -> {active, archived}``, ``active -> {paused, archived}``,
``paused -> {active, archived}``, ``archived -> {}`` (terminal, no way back).

**version+1 rule** (SoT A6.5 "활성 전략의 수정"): ``update_strategy`` bumps
``version`` only when the request includes a new ``config`` *and* the
strategy's current status is ``active`` — a name/description-only edit, or
any edit to a draft/paused strategy, leaves ``version`` untouched.

**Soft-delete active-strategy guard**: SoT B4.10 requires strategies be
soft-deleted, and SoT A6.5 implies an active strategy is still driving live
signal generation — ``delete_strategy`` reuses ``STRATEGY_INVALID_TRANSITION``
(no dedicated error code; issue #75's plan only adds two) to block deleting
an ``active`` strategy, the same way ``archived -> active`` is blocked.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any
from uuid import UUID

from src.domain.strategy import (
    ExecutionMode,
    Strategy,
    StrategyInfo,
    StrategyRepository,
    StrategyStatus,
)
from src.domain.strategy_template import STRATEGY_TEMPLATES, StrategyTemplate
from src.errors import ApiError, ErrorCode

_ALLOWED_TRANSITIONS: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    StrategyStatus.DRAFT: frozenset({StrategyStatus.ACTIVE, StrategyStatus.ARCHIVED}),
    StrategyStatus.ACTIVE: frozenset({StrategyStatus.PAUSED, StrategyStatus.ARCHIVED}),
    StrategyStatus.PAUSED: frozenset({StrategyStatus.ACTIVE, StrategyStatus.ARCHIVED}),
    StrategyStatus.ARCHIVED: frozenset(),
}


async def _get_owned_strategy(
    repo: StrategyRepository, *, user_id: UUID, strategy_id: UUID
) -> Strategy:
    strategy = await repo.get_by_id(user_id=user_id, strategy_id=strategy_id)
    if strategy is None:
        raise ApiError(
            status=404, code=ErrorCode.STRATEGY_NOT_FOUND, detail="Strategy not found."
        )
    return strategy


async def create_strategy(
    repo: StrategyRepository,
    *,
    user_id: UUID,
    name: str,
    description: str | None,
    execution_mode: ExecutionMode,
    config: dict[str, Any],
) -> Strategy:
    return await repo.create(
        info=StrategyInfo(
            user_id=user_id,
            name=name,
            description=description,
            execution_mode=execution_mode,
            config=config,
        )
    )


async def get_strategy(
    repo: StrategyRepository, *, user_id: UUID, strategy_id: UUID
) -> Strategy:
    return await _get_owned_strategy(repo, user_id=user_id, strategy_id=strategy_id)


async def list_strategies(
    repo: StrategyRepository, *, user_id: UUID, status: StrategyStatus | None
) -> Sequence[Strategy]:
    return await repo.list_by_user(user_id=user_id, status=status)


async def update_strategy(
    repo: StrategyRepository,
    *,
    user_id: UUID,
    strategy_id: UUID,
    name: str | None,
    description: str | None,
    execution_mode: ExecutionMode | None,
    config: dict[str, Any] | None,
) -> Strategy:
    strategy = await _get_owned_strategy(repo, user_id=user_id, strategy_id=strategy_id)

    if name is not None:
        strategy.name = name
    if description is not None:
        strategy.description = description
    if execution_mode is not None:
        strategy.execution_mode = execution_mode
    if config is not None:
        strategy.config = config
        if strategy.status == StrategyStatus.ACTIVE:
            strategy.version += 1

    return await repo.update(strategy)


async def _transition_status(
    repo: StrategyRepository, *, user_id: UUID, strategy_id: UUID, target: StrategyStatus
) -> Strategy:
    strategy = await _get_owned_strategy(repo, user_id=user_id, strategy_id=strategy_id)
    if target not in _ALLOWED_TRANSITIONS[strategy.status]:
        raise ApiError(
            status=409,
            code=ErrorCode.STRATEGY_INVALID_TRANSITION,
            detail=f"Cannot transition strategy from {strategy.status.value} to {target.value}.",
        )
    strategy.status = target
    return await repo.update(strategy)


async def activate_strategy(
    repo: StrategyRepository, *, user_id: UUID, strategy_id: UUID
) -> Strategy:
    return await _transition_status(
        repo, user_id=user_id, strategy_id=strategy_id, target=StrategyStatus.ACTIVE
    )


async def pause_strategy(
    repo: StrategyRepository, *, user_id: UUID, strategy_id: UUID
) -> Strategy:
    return await _transition_status(
        repo, user_id=user_id, strategy_id=strategy_id, target=StrategyStatus.PAUSED
    )


async def archive_strategy(
    repo: StrategyRepository, *, user_id: UUID, strategy_id: UUID
) -> Strategy:
    return await _transition_status(
        repo, user_id=user_id, strategy_id=strategy_id, target=StrategyStatus.ARCHIVED
    )


async def clone_strategy(
    repo: StrategyRepository, *, user_id: UUID, strategy_id: UUID
) -> Strategy:
    original = await _get_owned_strategy(repo, user_id=user_id, strategy_id=strategy_id)
    return await repo.create(
        info=StrategyInfo(
            user_id=user_id,
            name=f"{original.name} (복제)",
            description=original.description,
            execution_mode=original.execution_mode,
            config=deepcopy(original.config),
        )
    )


async def delete_strategy(
    repo: StrategyRepository, *, user_id: UUID, strategy_id: UUID
) -> None:
    strategy = await _get_owned_strategy(repo, user_id=user_id, strategy_id=strategy_id)
    if strategy.status == StrategyStatus.ACTIVE:
        raise ApiError(
            status=409,
            code=ErrorCode.STRATEGY_INVALID_TRANSITION,
            detail="Cannot delete an active strategy — pause or archive it first.",
        )
    await repo.soft_delete(strategy)


def list_templates() -> list[StrategyTemplate]:
    return STRATEGY_TEMPLATES
