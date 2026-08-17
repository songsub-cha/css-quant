"""GET /api/v1/scores — router-level tests (SoT A5.2/A6.1).

``TestClient`` + ``app.dependency_overrides``, same pattern as
``test_auth_login.py``: no DB container in this environment, so every port
is swapped for its in-memory fake.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src.api.deps import (
    get_asset_repository,
    get_asset_score_repository,
    get_secret_key,
    get_user_repository,
)
from src.domain.ai_score import AssetScoreInfo
from src.domain.asset import AssetType, Exchange, Market
from src.domain.ids import generate_uuid7
from src.domain.market_regime import RegimeStatus
from src.domain.security import hash_password
from src.domain.tokens import create_access_token
from src.domain.user import User
from src.main import app

from .conftest import FakeAssetRepository, FakeAssetScoreRepository, FakeUserRepository

_SECRET_KEY = "scores-api-test-secret-key-at-least-32-chars"
_DATE = date(2026, 8, 17)
_EARLIER_DATE = date(2026, 8, 14)


@pytest.fixture
def user_repo() -> FakeUserRepository:
    fake = FakeUserRepository()
    now = datetime.now(UTC)
    fake.users.append(
        User(
            id=generate_uuid7(),
            email="owner@example.com",
            password_hash=hash_password("correct horse battery staple"),
            created_at=now,
            updated_at=now,
        )
    )
    return fake


@pytest.fixture
def asset_repo() -> FakeAssetRepository:
    return FakeAssetRepository()


@pytest.fixture
def score_repo() -> FakeAssetScoreRepository:
    return FakeAssetScoreRepository()


@pytest.fixture
def client(
    user_repo: FakeUserRepository,
    asset_repo: FakeAssetRepository,
    score_repo: FakeAssetScoreRepository,
) -> Iterator[TestClient]:
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_asset_repository] = lambda: asset_repo
    app.dependency_overrides[get_asset_score_repository] = lambda: score_repo
    app.dependency_overrides[get_secret_key] = lambda: _SECRET_KEY
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_cookies(user_repo: FakeUserRepository) -> dict[str, str]:
    token = create_access_token(user_repo.users[0].id, secret_key=_SECRET_KEY)
    return {"at": token}


def test_list_scores_without_auth_cookie_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/scores")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_list_scores_cold_start_returns_null_date_and_empty_list(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.get("/api/v1/scores", cookies=auth_cookies)

    assert response.status_code == 200
    assert response.json() == {"score_date": None, "scores": []}


def test_list_scores_defaults_to_latest_date_ranked_descending(
    client: TestClient,
    auth_cookies: dict[str, str],
    asset_repo: FakeAssetRepository,
    score_repo: FakeAssetScoreRepository,
) -> None:
    async def _seed() -> None:
        low = await asset_repo.upsert_active(
            ticker="000001",
            name="Low Co",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        high = await asset_repo.upsert_active(
            ticker="000002",
            name="High Co",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        await score_repo.upsert(
            score=AssetScoreInfo(
                asset_id=low.id,
                score_date=_DATE,
                regime=RegimeStatus.NORMAL,
                total_score=Decimal("40.00"),
                momentum_score=Decimal("50.00"),
                quality_score=Decimal("50.00"),
                value_score=Decimal("50.00"),
                liquidity_score=Decimal("50.00"),
                risk_score=Decimal("50.00"),
                summary="약세 흐름",
                positive_reasons=["안정적 배당"],
                risk_reasons=["거래대금 부족"],
            )
        )
        await score_repo.upsert(
            score=AssetScoreInfo(
                asset_id=high.id,
                score_date=_DATE,
                regime=RegimeStatus.NORMAL,
                total_score=Decimal("90.00"),
                momentum_score=Decimal("95.00"),
                quality_score=Decimal("85.00"),
                value_score=Decimal("80.00"),
                liquidity_score=Decimal("90.00"),
                risk_score=Decimal("70.00"),
            )
        )

    asyncio.run(_seed())

    response = client.get("/api/v1/scores", cookies=auth_cookies)

    assert response.status_code == 200
    body = response.json()
    assert body["score_date"] == _DATE.isoformat()
    assert [item["ticker"] for item in body["scores"]] == ["000002", "000001"]

    top = body["scores"][0]
    assert top["asset_id"].startswith("ast_")
    assert top["name"] == "High Co"
    assert top["regime"] == "NORMAL"
    assert top["total_score"] == "90.00"

    bottom = body["scores"][1]
    assert bottom["summary"] == "약세 흐름"
    assert bottom["positive_reasons"] == ["안정적 배당"]
    assert bottom["risk_reasons"] == ["거래대금 부족"]


def test_list_scores_with_specific_date_returns_that_date(
    client: TestClient,
    auth_cookies: dict[str, str],
    asset_repo: FakeAssetRepository,
    score_repo: FakeAssetScoreRepository,
) -> None:
    async def _seed() -> None:
        asset = await asset_repo.upsert_active(
            ticker="000001",
            name="A Co",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        await score_repo.upsert(
            score=AssetScoreInfo(
                asset_id=asset.id,
                score_date=_EARLIER_DATE,
                regime=RegimeStatus.DEFENSIVE,
                total_score=Decimal("30.00"),
                momentum_score=Decimal("30.00"),
                quality_score=Decimal("30.00"),
                value_score=Decimal("30.00"),
                liquidity_score=Decimal("30.00"),
                risk_score=Decimal("30.00"),
            )
        )
        await score_repo.upsert(
            score=AssetScoreInfo(
                asset_id=asset.id,
                score_date=_DATE,
                regime=RegimeStatus.NORMAL,
                total_score=Decimal("70.00"),
                momentum_score=Decimal("70.00"),
                quality_score=Decimal("70.00"),
                value_score=Decimal("70.00"),
                liquidity_score=Decimal("70.00"),
                risk_score=Decimal("70.00"),
            )
        )

    asyncio.run(_seed())

    response = client.get(
        "/api/v1/scores", params={"score_date": _EARLIER_DATE.isoformat()}, cookies=auth_cookies
    )

    assert response.status_code == 200
    body = response.json()
    assert body["score_date"] == _EARLIER_DATE.isoformat()
    assert len(body["scores"]) == 1
    assert body["scores"][0]["regime"] == "DEFENSIVE"


def test_list_scores_with_date_that_has_no_rows_returns_empty_list_not_error(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.get(
        "/api/v1/scores", params={"score_date": _DATE.isoformat()}, cookies=auth_cookies
    )

    assert response.status_code == 200
    assert response.json() == {"score_date": _DATE.isoformat(), "scores": []}
