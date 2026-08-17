"""``list_ranked_scores`` pure unit tests (SoT A5.2/A6.1 — services layer).

No DB container in this environment: exercised against
``conftest.FakeAssetScoreRepository``/``FakeAssetRepository``, the same
isolation approach ``test_asset_sync.py`` uses. Uses ``asyncio.run`` directly
(no pytest-asyncio dependency in this project).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from uuid import UUID

from src.domain.ai_score import AssetScoreInfo
from src.domain.asset import Asset, AssetType, Exchange, Market
from src.domain.market_regime import RegimeStatus
from src.services.scores import list_ranked_scores

from .conftest import FakeAssetRepository, FakeAssetScoreRepository

_DATE = date(2026, 8, 17)
_EARLIER_DATE = date(2026, 8, 14)


def _score_info(
    asset_id: UUID,
    score_date: date,
    total_score: Decimal,
    *,
    regime: RegimeStatus = RegimeStatus.NORMAL,
) -> AssetScoreInfo:
    return AssetScoreInfo(
        asset_id=asset_id,
        score_date=score_date,
        regime=regime,
        total_score=total_score,
        momentum_score=Decimal("50.00"),
        quality_score=Decimal("50.00"),
        value_score=Decimal("50.00"),
        liquidity_score=Decimal("50.00"),
        risk_score=Decimal("50.00"),
    )


async def _seed_asset(asset_repo: FakeAssetRepository, ticker: str, name: str) -> Asset:
    return await asset_repo.upsert_active(
        ticker=ticker,
        name=name,
        market=Market.KR,
        asset_type=AssetType.STOCK,
        exchange=Exchange.KOSPI,
    )


def test_list_ranked_scores_sorts_by_total_score_descending() -> None:
    async def _run() -> None:
        score_repo = FakeAssetScoreRepository()
        asset_repo = FakeAssetRepository()
        low = await _seed_asset(asset_repo, "000001", "Low Co")
        high = await _seed_asset(asset_repo, "000002", "High Co")
        await score_repo.upsert(score=_score_info(low.id, _DATE, Decimal("40.00")))
        await score_repo.upsert(score=_score_info(high.id, _DATE, Decimal("90.00")))

        resolved_date, pairs = await list_ranked_scores(
            score_repo, asset_repo, score_date=_DATE
        )

        assert resolved_date == _DATE
        assert [asset.ticker for _score, asset in pairs] == ["000002", "000001"]

    asyncio.run(_run())


def test_list_ranked_scores_breaks_ties_by_asset_id_ascending() -> None:
    async def _run() -> None:
        score_repo = FakeAssetScoreRepository()
        asset_repo = FakeAssetRepository()
        a = await _seed_asset(asset_repo, "000001", "A Co")
        b = await _seed_asset(asset_repo, "000002", "B Co")
        await score_repo.upsert(score=_score_info(a.id, _DATE, Decimal("50.00")))
        await score_repo.upsert(score=_score_info(b.id, _DATE, Decimal("50.00")))

        _resolved_date, pairs = await list_ranked_scores(
            score_repo, asset_repo, score_date=_DATE
        )

        expected_order = sorted([a.id, b.id])
        assert [asset.id for _score, asset in pairs] == expected_order

    asyncio.run(_run())


def test_list_ranked_scores_defaults_to_latest_score_date() -> None:
    async def _run() -> None:
        score_repo = FakeAssetScoreRepository()
        asset_repo = FakeAssetRepository()
        asset = await _seed_asset(asset_repo, "000001", "A Co")
        await score_repo.upsert(score=_score_info(asset.id, _EARLIER_DATE, Decimal("30.00")))
        await score_repo.upsert(score=_score_info(asset.id, _DATE, Decimal("70.00")))

        resolved_date, pairs = await list_ranked_scores(score_repo, asset_repo, score_date=None)

        assert resolved_date == _DATE
        assert len(pairs) == 1
        assert pairs[0][0].total_score == Decimal("70.00")

    asyncio.run(_run())


def test_list_ranked_scores_cold_start_returns_none_and_empty_list() -> None:
    async def _run() -> None:
        score_repo = FakeAssetScoreRepository()
        asset_repo = FakeAssetRepository()

        resolved_date, pairs = await list_ranked_scores(score_repo, asset_repo, score_date=None)

        assert resolved_date is None
        assert pairs == []

    asyncio.run(_run())


def test_list_ranked_scores_specific_date_with_no_rows_returns_empty_list_not_error() -> None:
    async def _run() -> None:
        score_repo = FakeAssetScoreRepository()
        asset_repo = FakeAssetRepository()
        asset = await _seed_asset(asset_repo, "000001", "A Co")
        await score_repo.upsert(score=_score_info(asset.id, _EARLIER_DATE, Decimal("30.00")))

        resolved_date, pairs = await list_ranked_scores(
            score_repo, asset_repo, score_date=_DATE
        )

        assert resolved_date == _DATE
        assert pairs == []

    asyncio.run(_run())
