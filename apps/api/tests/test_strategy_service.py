"""``src.services.strategy`` pure unit tests (SoT A5.3/A6.5 — services layer).

No DB container in this environment: exercised against
``conftest.FakeStrategyRepository``, the same isolation approach
``test_watchlist_service.py`` uses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest

from src.domain.strategy import ExecutionMode, Strategy, StrategyStatus
from src.errors import ApiError
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

from .conftest import FakeStrategyRepository


def test_create_strategy_starts_as_draft_version_1() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()

        strategy = await create_strategy(
            repo,
            user_id=user_id,
            name="전략 A",
            description=None,
            execution_mode=ExecutionMode.BACKTEST,
            config={},
        )

        assert strategy.status == StrategyStatus.DRAFT
        assert strategy.version == 1
        assert strategy.user_id == user_id

    asyncio.run(_run())


def test_get_strategy_raises_404_for_nonexistent_id() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()

        with pytest.raises(ApiError) as exc_info:
            await get_strategy(repo, user_id=uuid4(), strategy_id=uuid4())

        assert exc_info.value.status == 404
        assert exc_info.value.code.value == "STRATEGY_NOT_FOUND"

    asyncio.run(_run())


def test_get_strategy_raises_404_for_other_users_strategy() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        owner = uuid4()
        strategy = await create_strategy(
            repo,
            user_id=owner,
            name="전략",
            description=None,
            execution_mode=ExecutionMode.BACKTEST,
            config={},
        )

        with pytest.raises(ApiError) as exc_info:
            await get_strategy(repo, user_id=uuid4(), strategy_id=strategy.id)

        assert exc_info.value.status == 404

    asyncio.run(_run())


def test_list_strategies_filters_by_status() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()
        draft = await create_strategy(
            repo,
            user_id=user_id,
            name="드래프트",
            description=None,
            execution_mode=ExecutionMode.BACKTEST,
            config={},
        )
        active = await create_strategy(
            repo,
            user_id=user_id,
            name="활성",
            description=None,
            execution_mode=ExecutionMode.BACKTEST,
            config={},
        )
        await activate_strategy(repo, user_id=user_id, strategy_id=active.id)

        all_strategies = await list_strategies(repo, user_id=user_id, status=None)
        active_only = await list_strategies(repo, user_id=user_id, status=StrategyStatus.ACTIVE)

        assert {s.id for s in all_strategies} == {draft.id, active.id}
        assert [s.id for s in active_only] == [active.id]

    asyncio.run(_run())


def test_update_strategy_bumps_version_when_active_and_config_included() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()
        strategy = await create_strategy(
            repo,
            user_id=user_id,
            name="전략",
            description=None,
            execution_mode=ExecutionMode.BACKTEST,
            config={},
        )
        await activate_strategy(repo, user_id=user_id, strategy_id=strategy.id)

        updated = await update_strategy(
            repo,
            user_id=user_id,
            strategy_id=strategy.id,
            name=None,
            description=None,
            execution_mode=None,
            config={"ai_filter": {"min_score": "80"}},
        )

        assert updated.version == 2
        assert updated.config == {"ai_filter": {"min_score": "80"}}

    asyncio.run(_run())


def test_update_strategy_does_not_bump_version_when_draft() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()
        strategy = await create_strategy(
            repo,
            user_id=user_id,
            name="전략",
            description=None,
            execution_mode=ExecutionMode.BACKTEST,
            config={},
        )

        updated = await update_strategy(
            repo,
            user_id=user_id,
            strategy_id=strategy.id,
            name=None,
            description=None,
            execution_mode=None,
            config={"ai_filter": {"min_score": "80"}},
        )

        assert updated.version == 1

    asyncio.run(_run())


def test_update_strategy_name_only_never_bumps_version_even_when_active() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()
        strategy = await create_strategy(
            repo,
            user_id=user_id,
            name="전략",
            description=None,
            execution_mode=ExecutionMode.BACKTEST,
            config={},
        )
        await activate_strategy(repo, user_id=user_id, strategy_id=strategy.id)

        updated = await update_strategy(
            repo,
            user_id=user_id,
            strategy_id=strategy.id,
            name="새 이름",
            description=None,
            execution_mode=None,
            config=None,
        )

        assert updated.version == 1
        assert updated.name == "새 이름"

    asyncio.run(_run())


def test_update_strategy_paused_with_config_does_not_bump_version() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()
        strategy = await create_strategy(
            repo,
            user_id=user_id,
            name="전략",
            description=None,
            execution_mode=ExecutionMode.BACKTEST,
            config={},
        )
        await activate_strategy(repo, user_id=user_id, strategy_id=strategy.id)
        await pause_strategy(repo, user_id=user_id, strategy_id=strategy.id)

        updated = await update_strategy(
            repo,
            user_id=user_id,
            strategy_id=strategy.id,
            name=None,
            description=None,
            execution_mode=None,
            config={"ai_filter": {"min_score": "90"}},
        )

        assert updated.version == 1

    asyncio.run(_run())


@pytest.mark.parametrize(
    ("start", "transition_fn"),
    [
        (StrategyStatus.ARCHIVED, activate_strategy),
        (StrategyStatus.DRAFT, pause_strategy),
    ],
)
def test_invalid_transitions_raise_409(
    start: StrategyStatus,
    transition_fn: Callable[..., Awaitable[Strategy]],
) -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()
        strategy = await create_strategy(
            repo,
            user_id=user_id,
            name="전략",
            description=None,
            execution_mode=ExecutionMode.BACKTEST,
            config={},
        )
        if start == StrategyStatus.ARCHIVED:
            await archive_strategy(repo, user_id=user_id, strategy_id=strategy.id)

        with pytest.raises(ApiError) as exc_info:
            await transition_fn(repo, user_id=user_id, strategy_id=strategy.id)

        assert exc_info.value.status == 409
        assert exc_info.value.code.value == "STRATEGY_INVALID_TRANSITION"

    asyncio.run(_run())


def test_full_transition_table_all_allowed_paths_succeed() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()

        draft_to_active = await create_strategy(
            repo, user_id=user_id, name="a", description=None,
            execution_mode=ExecutionMode.BACKTEST, config={},
        )
        activated = await activate_strategy(repo, user_id=user_id, strategy_id=draft_to_active.id)
        assert activated.status == StrategyStatus.ACTIVE

        paused = await pause_strategy(repo, user_id=user_id, strategy_id=activated.id)
        assert paused.status == StrategyStatus.PAUSED

        reactivated = await activate_strategy(repo, user_id=user_id, strategy_id=paused.id)
        assert reactivated.status == StrategyStatus.ACTIVE

        archived = await archive_strategy(repo, user_id=user_id, strategy_id=reactivated.id)
        assert archived.status == StrategyStatus.ARCHIVED

    asyncio.run(_run())


def test_clone_strategy_creates_independent_draft_copy() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()
        original = await create_strategy(
            repo,
            user_id=user_id,
            name="원본 전략",
            description="설명",
            execution_mode=ExecutionMode.PAPER,
            config={"ai_filter": {"min_score": "70"}},
        )
        await activate_strategy(repo, user_id=user_id, strategy_id=original.id)

        cloned = await clone_strategy(repo, user_id=user_id, strategy_id=original.id)

        assert cloned.id != original.id
        assert cloned.name == "원본 전략 (복제)"
        assert cloned.status == StrategyStatus.DRAFT
        assert cloned.version == 1
        assert cloned.config == original.config

        # Mutating the clone's config must not affect the original (independent object).
        cloned.config["ai_filter"]["min_score"] = "99"
        current_original = await get_strategy(repo, user_id=user_id, strategy_id=original.id)
        assert current_original.config == {"ai_filter": {"min_score": "70"}}

    asyncio.run(_run())


def test_delete_strategy_blocks_active_strategy_with_409() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()
        strategy = await create_strategy(
            repo, user_id=user_id, name="전략", description=None,
            execution_mode=ExecutionMode.BACKTEST, config={},
        )
        await activate_strategy(repo, user_id=user_id, strategy_id=strategy.id)

        with pytest.raises(ApiError) as exc_info:
            await delete_strategy(repo, user_id=user_id, strategy_id=strategy.id)

        assert exc_info.value.status == 409
        assert exc_info.value.code.value == "STRATEGY_INVALID_TRANSITION"

    asyncio.run(_run())


def test_delete_strategy_soft_deletes_draft_strategy() -> None:
    async def _run() -> None:
        repo = FakeStrategyRepository()
        user_id = uuid4()
        strategy = await create_strategy(
            repo, user_id=user_id, name="전략", description=None,
            execution_mode=ExecutionMode.BACKTEST, config={},
        )

        await delete_strategy(repo, user_id=user_id, strategy_id=strategy.id)

        with pytest.raises(ApiError) as exc_info:
            await get_strategy(repo, user_id=user_id, strategy_id=strategy.id)
        assert exc_info.value.status == 404

        remaining = await list_strategies(repo, user_id=user_id, status=None)
        assert remaining == []

    asyncio.run(_run())


def test_list_templates_returns_four_seeded_templates() -> None:
    templates = list_templates()

    assert len(templates) == 4
    assert {t.key for t in templates} == {
        "trend_following",
        "ai_momentum",
        "low_volatility_etf",
        "large_cap_quality",
    }
