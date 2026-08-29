"""Worker-level orchestration tests for ``calculate_scores`` (SoT A6.1 stages 3/4/6).

Exercises ``src.workers.score_calculation.calculate_scores`` against
``tests/conftest.py``'s in-memory fakes — no live DB, same shape as
``test_market_regime_detection.py``/``test_factor_calculation_worker.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from src.domain.ai_score import FactorWeights, MissingRegimeError, RegimeWeightProfile
from src.domain.asset_factor import AssetFactorInfo
from src.domain.market_regime import MarketRegimeInfo, RegimeStatus
from src.workers.score_calculation import calculate_scores

from .conftest import (
    FakeAssetFactorRepository,
    FakeAssetScoreRepository,
    FakeMarketRegimeRepository,
)

_WEIGHTS = RegimeWeightProfile(
    normal=FactorWeights(
        momentum=Decimal("0.35"),
        quality=Decimal("0.25"),
        value=Decimal("0.20"),
        liquidity=Decimal("0.10"),
        risk=Decimal("0.10"),
    ),
    defensive=FactorWeights(
        momentum=Decimal("0.15"),
        quality=Decimal("0.35"),
        value=Decimal("0.20"),
        liquidity=Decimal("0.10"),
        risk=Decimal("0.20"),
    ),
)
_HOLD_THRESHOLD = 3


def _factor_info(
    asset_id: UUID,
    factor_date: date,
    *,
    momentum_3m: Decimal | None = Decimal(0),
    momentum_6m: Decimal | None = Decimal(0),
    dist_52w_high: Decimal | None = Decimal(0),
    ma20_deviation: Decimal | None = Decimal(0),
    roe: Decimal | None = Decimal(0),
    op_margin: Decimal | None = Decimal(0),
    revenue_growth_yoy: Decimal | None = Decimal(0),
    debt_ratio: Decimal | None = Decimal(0),
    per: Decimal | None = Decimal(10),
    pbr: Decimal | None = Decimal(1),
) -> AssetFactorInfo:
    return AssetFactorInfo(
        asset_id=asset_id,
        factor_date=factor_date,
        momentum_3m=momentum_3m,
        momentum_6m=momentum_6m,
        dist_52w_high=dist_52w_high,
        ma20_deviation=ma20_deviation,
        roe=roe,
        op_margin=op_margin,
        revenue_growth_yoy=revenue_growth_yoy,
        debt_ratio=debt_ratio,
        per=per,
        pbr=pbr,
        avg_trading_value_20d=Decimal(1_000_000_000),
        volume_cv=Decimal("0.2"),
        volatility_60d=Decimal("0.1"),
        mdd_60d=Decimal("-0.05"),
        gap_frequency_60d=Decimal("0.01"),
        market_cap=Decimal(400_000_000_000),
        is_managed=False,
        is_alert=False,
        financial_data_as_of=None,
    )


def _regime_info(
    regime_date: date, regime: RegimeStatus = RegimeStatus.NORMAL
) -> MarketRegimeInfo:
    return MarketRegimeInfo(
        regime_date=regime_date,
        regime=regime,
        kospi_close=Decimal(2500),
        kospi_ma200=Decimal(2400),
        vkospi=Decimal(20),
        kospi_volatility_20d=Decimal("0.01"),
        market_shock=False,
        signals={},
    )


def test_calculate_scores_fetches_normalizes_and_upserts() -> None:
    async def _run() -> None:
        factor_repo = FakeAssetFactorRepository()
        regime_repo = FakeMarketRegimeRepository()
        score_repo = FakeAssetScoreRepository()
        as_of = date(2026, 8, 16)
        asset_a, asset_b = uuid4(), uuid4()
        await factor_repo.upsert(
            factor=_factor_info(asset_a, as_of, momentum_3m=Decimal(10))
        )
        await factor_repo.upsert(
            factor=_factor_info(asset_b, as_of, momentum_3m=Decimal(5))
        )
        await regime_repo.upsert(regime=_regime_info(as_of, RegimeStatus.NORMAL))

        result = await calculate_scores(
            factor_repo,
            regime_repo,
            score_repo,
            as_of_date=as_of,
            weights=_WEIGHTS,
            missing_factor_hold_threshold=_HOLD_THRESHOLD,
        )

        assert {row.asset_id for row in result} == {asset_a, asset_b}
        assert len(score_repo.scores) == 2
        assert all(row.regime == RegimeStatus.NORMAL for row in score_repo.scores)
        assert all(row.total_score is not None for row in score_repo.scores)

    asyncio.run(_run())


def test_calculate_scores_returns_empty_when_no_factors_for_the_day() -> None:
    async def _run() -> None:
        factor_repo = FakeAssetFactorRepository()
        regime_repo = FakeMarketRegimeRepository()
        score_repo = FakeAssetScoreRepository()

        result = await calculate_scores(
            factor_repo,
            regime_repo,
            score_repo,
            as_of_date=date(2026, 8, 16),
            weights=_WEIGHTS,
            missing_factor_hold_threshold=_HOLD_THRESHOLD,
        )

        assert result == []
        assert score_repo.scores == []

    asyncio.run(_run())


def test_calculate_scores_raises_missing_regime_error_when_regime_not_recorded() -> None:
    async def _run() -> None:
        factor_repo = FakeAssetFactorRepository()
        regime_repo = FakeMarketRegimeRepository()
        score_repo = FakeAssetScoreRepository()
        as_of = date(2026, 8, 16)
        await factor_repo.upsert(factor=_factor_info(uuid4(), as_of))
        # regime_repo left empty for as_of — fail-closed (SoT A2 원칙 8).

        with pytest.raises(MissingRegimeError):
            await calculate_scores(
                factor_repo,
                regime_repo,
                score_repo,
                as_of_date=as_of,
                weights=_WEIGHTS,
                missing_factor_hold_threshold=_HOLD_THRESHOLD,
            )

    asyncio.run(_run())


def test_held_asset_gets_no_ai_scores_row() -> None:
    async def _run() -> None:
        factor_repo = FakeAssetFactorRepository()
        regime_repo = FakeMarketRegimeRepository()
        score_repo = FakeAssetScoreRepository()
        as_of = date(2026, 8, 16)
        held_asset, ok_asset = uuid4(), uuid4()
        await factor_repo.upsert(
            factor=_factor_info(
                held_asset,
                as_of,
                momentum_3m=None,
                momentum_6m=None,
                dist_52w_high=None,
                ma20_deviation=None,
                roe=None,
                op_margin=None,
                revenue_growth_yoy=None,
                debt_ratio=None,
                per=None,
                pbr=None,
            )
        )
        await factor_repo.upsert(factor=_factor_info(ok_asset, as_of))
        await regime_repo.upsert(regime=_regime_info(as_of, RegimeStatus.NORMAL))

        result = await calculate_scores(
            factor_repo,
            regime_repo,
            score_repo,
            as_of_date=as_of,
            weights=_WEIGHTS,
            missing_factor_hold_threshold=_HOLD_THRESHOLD,
        )

        assert {row.asset_id for row in result} == {ok_asset}
        assert {row.asset_id for row in score_repo.scores} == {ok_asset}

    asyncio.run(_run())


def test_rerun_is_idempotent_updates_existing_row_not_a_duplicate() -> None:
    async def _run() -> None:
        factor_repo = FakeAssetFactorRepository()
        regime_repo = FakeMarketRegimeRepository()
        score_repo = FakeAssetScoreRepository()
        as_of = date(2026, 8, 16)
        asset_id = uuid4()
        await factor_repo.upsert(factor=_factor_info(asset_id, as_of))
        await regime_repo.upsert(regime=_regime_info(as_of, RegimeStatus.NORMAL))

        await calculate_scores(
            factor_repo,
            regime_repo,
            score_repo,
            as_of_date=as_of,
            weights=_WEIGHTS,
            missing_factor_hold_threshold=_HOLD_THRESHOLD,
        )
        await calculate_scores(
            factor_repo,
            regime_repo,
            score_repo,
            as_of_date=as_of,
            weights=_WEIGHTS,
            missing_factor_hold_threshold=_HOLD_THRESHOLD,
        )

        assert len(score_repo.scores) == 1
        assert score_repo.scores[0].asset_id == asset_id

    asyncio.run(_run())
