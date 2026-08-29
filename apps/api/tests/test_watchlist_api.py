"""POST/GET/DELETE /api/v1/watchlist — router-level tests (SoT A5.2).

``TestClient`` + ``app.dependency_overrides``, same pattern as
``test_scores_api.py``: no DB container in this environment, so every port
is swapped for its in-memory fake.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.api.deps import (
    get_asset_repository,
    get_secret_key,
    get_user_repository,
    get_watchlist_item_repository,
)
from src.domain.asset import Asset, AssetType, Exchange, Market
from src.domain.ids import generate_uuid7
from src.domain.security import hash_password
from src.domain.tokens import create_access_token
from src.domain.user import User
from src.main import app

from .conftest import FakeAssetRepository, FakeUserRepository, FakeWatchlistItemRepository

_SECRET_KEY = "watchlist-api-test-secret-key-at-least-32-chars"


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
def watchlist_repo() -> FakeWatchlistItemRepository:
    return FakeWatchlistItemRepository()


@pytest.fixture
def client(
    user_repo: FakeUserRepository,
    asset_repo: FakeAssetRepository,
    watchlist_repo: FakeWatchlistItemRepository,
) -> Iterator[TestClient]:
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_asset_repository] = lambda: asset_repo
    app.dependency_overrides[get_watchlist_item_repository] = lambda: watchlist_repo
    app.dependency_overrides[get_secret_key] = lambda: _SECRET_KEY
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_cookies(user_repo: FakeUserRepository) -> dict[str, str]:
    token = create_access_token(user_repo.users[0].id, secret_key=_SECRET_KEY)
    return {"at": token}


async def _seed_asset(asset_repo: FakeAssetRepository, ticker: str = "005930") -> Asset:
    return await asset_repo.upsert_active(
        ticker=ticker,
        name="삼성전자",
        market=Market.KR,
        asset_type=AssetType.STOCK,
        exchange=Exchange.KOSPI,
    )


def test_endpoints_without_auth_cookie_return_401(client: TestClient) -> None:
    post_response = client.post(
        "/api/v1/watchlist", json={"asset_id": "ast_x", "kind": "watch"}
    )
    assert post_response.status_code == 401
    assert client.get("/api/v1/watchlist").status_code == 401
    assert client.delete("/api/v1/watchlist/ast_x").status_code == 401


def test_add_item_with_unknown_asset_id_returns_404(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    unknown_id = f"ast_{generate_uuid7()}"

    response = client.post(
        "/api/v1/watchlist",
        json={"asset_id": unknown_id, "kind": "watch"},
        cookies=auth_cookies,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ASSET_NOT_FOUND"


def test_add_item_with_malformed_asset_id_returns_422(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/watchlist",
        json={"asset_id": "not-a-prefixed-id", "kind": "watch"},
        cookies=auth_cookies,
    )

    assert response.status_code == 422


def test_add_then_get_then_delete_round_trip(
    client: TestClient,
    auth_cookies: dict[str, str],
    asset_repo: FakeAssetRepository,
) -> None:
    asset = asyncio.run(_seed_asset(asset_repo))
    asset_id_str = f"ast_{asset.id}"

    add_response = client.post(
        "/api/v1/watchlist",
        json={"asset_id": asset_id_str, "kind": "watch", "note": "관심 종목"},
        cookies=auth_cookies,
    )
    assert add_response.status_code == 200
    body = add_response.json()
    assert body["asset_id"] == asset_id_str
    assert body["kind"] == "watch"
    assert body["note"] == "관심 종목"
    assert body["id"].startswith("wl_")

    list_response = client.get("/api/v1/watchlist", cookies=auth_cookies)
    assert list_response.status_code == 200
    items = list_response.json()
    assert len(items) == 1
    assert items[0]["asset_id"] == asset_id_str
    assert items[0]["ticker"] == asset.ticker
    assert items[0]["name"] == asset.name

    delete_response = client.delete(f"/api/v1/watchlist/{asset_id_str}", cookies=auth_cookies)
    assert delete_response.status_code == 204

    list_after_delete = client.get("/api/v1/watchlist", cookies=auth_cookies)
    assert list_after_delete.json() == []


def test_re_add_same_asset_updates_kind_not_duplicates_row(
    client: TestClient,
    auth_cookies: dict[str, str],
    asset_repo: FakeAssetRepository,
) -> None:
    asset = asyncio.run(_seed_asset(asset_repo))
    asset_id_str = f"ast_{asset.id}"

    client.post(
        "/api/v1/watchlist",
        json={"asset_id": asset_id_str, "kind": "watch"},
        cookies=auth_cookies,
    )
    second = client.post(
        "/api/v1/watchlist",
        json={"asset_id": asset_id_str, "kind": "exclude"},
        cookies=auth_cookies,
    )
    assert second.status_code == 200
    assert second.json()["kind"] == "exclude"

    items = client.get("/api/v1/watchlist", cookies=auth_cookies).json()
    assert len(items) == 1
    assert items[0]["kind"] == "exclude"


def test_list_filters_by_kind_query_param(
    client: TestClient,
    auth_cookies: dict[str, str],
    asset_repo: FakeAssetRepository,
) -> None:
    watched = asyncio.run(_seed_asset(asset_repo, ticker="000001"))
    excluded = asyncio.run(_seed_asset(asset_repo, ticker="000002"))
    client.post(
        "/api/v1/watchlist",
        json={"asset_id": f"ast_{watched.id}", "kind": "watch"},
        cookies=auth_cookies,
    )
    client.post(
        "/api/v1/watchlist",
        json={"asset_id": f"ast_{excluded.id}", "kind": "exclude"},
        cookies=auth_cookies,
    )

    response = client.get("/api/v1/watchlist", params={"kind": "exclude"}, cookies=auth_cookies)

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["asset_id"] == f"ast_{excluded.id}"
    assert items[0]["ticker"] == excluded.ticker
    assert items[0]["name"] == excluded.name


def test_delete_nonexistent_item_is_idempotent_204(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.delete(f"/api/v1/watchlist/ast_{generate_uuid7()}", cookies=auth_cookies)

    assert response.status_code == 204
