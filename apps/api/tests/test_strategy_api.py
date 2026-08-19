"""POST/GET/PATCH/DELETE + action /api/v1/strategies — router-level tests (SoT A5.3).

``TestClient`` + ``app.dependency_overrides``, same pattern as
``test_watchlist_api.py``: no DB container in this environment, so the
strategy repository port is swapped for its in-memory fake.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.api.deps import get_secret_key, get_strategy_repository, get_user_repository
from src.domain.ids import generate_uuid7
from src.domain.security import hash_password
from src.domain.strategy import ExecutionMode, StrategyInfo
from src.domain.tokens import create_access_token
from src.domain.user import User
from src.main import app

from .conftest import FakeStrategyRepository, FakeUserRepository

_SECRET_KEY = "strategy-api-test-secret-key-at-least-32-chars"


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
def strategy_repo() -> FakeStrategyRepository:
    return FakeStrategyRepository()


@pytest.fixture
def client(
    user_repo: FakeUserRepository, strategy_repo: FakeStrategyRepository
) -> Iterator[TestClient]:
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_strategy_repository] = lambda: strategy_repo
    app.dependency_overrides[get_secret_key] = lambda: _SECRET_KEY
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_cookies(user_repo: FakeUserRepository) -> dict[str, str]:
    token = create_access_token(user_repo.users[0].id, secret_key=_SECRET_KEY)
    return {"at": token}


def test_endpoints_without_auth_cookie_return_401(client: TestClient) -> None:
    create_response = client.post(
        "/api/v1/strategies", json={"name": "x", "execution_mode": "backtest"}
    )
    assert create_response.status_code == 401
    assert client.get("/api/v1/strategies").status_code == 401
    assert client.get("/api/v1/strategies/templates").status_code == 401
    unknown = f"str_{generate_uuid7()}"
    assert client.get(f"/api/v1/strategies/{unknown}").status_code == 401
    assert client.delete(f"/api/v1/strategies/{unknown}").status_code == 401


def test_create_with_invalid_config_returns_422(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/strategies",
        json={
            "name": "잘못된 전략",
            "execution_mode": "backtest",
            "config": {"ai_filter": {"min_score": 150}},
        },
        cookies=auth_cookies,
    )

    assert response.status_code == 422


def test_get_nonexistent_strategy_returns_404(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    unknown_id = f"str_{generate_uuid7()}"

    response = client.get(f"/api/v1/strategies/{unknown_id}", cookies=auth_cookies)

    assert response.status_code == 404
    assert response.json()["code"] == "STRATEGY_NOT_FOUND"


def test_get_other_users_strategy_returns_404_idor_safe(
    client: TestClient,
    auth_cookies: dict[str, str],
    strategy_repo: FakeStrategyRepository,
) -> None:
    other_user_id = generate_uuid7()

    async def _seed() -> str:
        row = await strategy_repo.create(
            info=StrategyInfo(
                user_id=other_user_id,
                name="타인 전략",
                description=None,
                execution_mode=ExecutionMode.BACKTEST,
                config={},
            )
        )
        return f"str_{row.id}"

    strategy_id_str = asyncio.run(_seed())

    response = client.get(f"/api/v1/strategies/{strategy_id_str}", cookies=auth_cookies)

    assert response.status_code == 404


def test_templates_endpoint_does_not_collide_with_strategy_id_route(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.get("/api/v1/strategies/templates", cookies=auth_cookies)

    assert response.status_code == 200
    templates = response.json()
    assert len(templates) == 4
    assert {t["key"] for t in templates} == {
        "trend_following",
        "ai_momentum",
        "low_volatility_etf",
        "large_cap_quality",
    }


def test_full_round_trip_create_activate_update_pause_archive(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/v1/strategies",
        json={
            "name": "테스트 전략",
            "description": "설명",
            "execution_mode": "backtest",
            "config": {"ai_filter": {"min_score": 70, "top_n": 15}},
        },
        cookies=auth_cookies,
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["status"] == "draft"
    assert body["version"] == 1
    assert body["id"].startswith("str_")
    strategy_id = body["id"]

    activate_response = client.post(
        f"/api/v1/strategies/{strategy_id}/activate", cookies=auth_cookies
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["status"] == "active"

    update_response = client.patch(
        f"/api/v1/strategies/{strategy_id}",
        json={"config": {"ai_filter": {"min_score": 80, "top_n": 15}}},
        cookies=auth_cookies,
    )
    assert update_response.status_code == 200
    assert update_response.json()["version"] == 2
    assert update_response.json()["config"]["ai_filter"]["min_score"] == "80"

    pause_response = client.post(f"/api/v1/strategies/{strategy_id}/pause", cookies=auth_cookies)
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"

    archive_response = client.post(
        f"/api/v1/strategies/{strategy_id}/archive", cookies=auth_cookies
    )
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"

    list_response = client.get("/api/v1/strategies", cookies=auth_cookies)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_invalid_transition_returns_409(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/v1/strategies",
        json={"name": "전략", "execution_mode": "backtest"},
        cookies=auth_cookies,
    )
    strategy_id = create_response.json()["id"]

    response = client.post(f"/api/v1/strategies/{strategy_id}/pause", cookies=auth_cookies)

    assert response.status_code == 409
    assert response.json()["code"] == "STRATEGY_INVALID_TRANSITION"


def test_clone_creates_independent_draft_copy(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/v1/strategies",
        json={
            "name": "원본",
            "execution_mode": "backtest",
            "config": {"ai_filter": {"min_score": 70}},
        },
        cookies=auth_cookies,
    )
    strategy_id = create_response.json()["id"]
    client.post(f"/api/v1/strategies/{strategy_id}/activate", cookies=auth_cookies)

    clone_response = client.post(f"/api/v1/strategies/{strategy_id}/clone", cookies=auth_cookies)

    assert clone_response.status_code == 200
    cloned = clone_response.json()
    assert cloned["id"] != strategy_id
    assert cloned["name"] == "원본 (복제)"
    assert cloned["status"] == "draft"
    assert cloned["version"] == 1


def test_delete_active_strategy_returns_409(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/v1/strategies",
        json={"name": "전략", "execution_mode": "backtest"},
        cookies=auth_cookies,
    )
    strategy_id = create_response.json()["id"]
    client.post(f"/api/v1/strategies/{strategy_id}/activate", cookies=auth_cookies)

    response = client.delete(f"/api/v1/strategies/{strategy_id}", cookies=auth_cookies)

    assert response.status_code == 409
    assert response.json()["code"] == "STRATEGY_INVALID_TRANSITION"


def test_delete_draft_strategy_returns_204_and_excludes_from_list(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    create_response = client.post(
        "/api/v1/strategies",
        json={"name": "전략", "execution_mode": "backtest"},
        cookies=auth_cookies,
    )
    strategy_id = create_response.json()["id"]

    delete_response = client.delete(f"/api/v1/strategies/{strategy_id}", cookies=auth_cookies)
    assert delete_response.status_code == 204

    get_response = client.get(f"/api/v1/strategies/{strategy_id}", cookies=auth_cookies)
    assert get_response.status_code == 404

    list_response = client.get("/api/v1/strategies", cookies=auth_cookies)
    assert list_response.json() == []


def test_list_filters_by_status_query_param(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    client.post(
        "/api/v1/strategies",
        json={"name": "드래프트", "execution_mode": "backtest"},
        cookies=auth_cookies,
    )
    second = client.post(
        "/api/v1/strategies",
        json={"name": "활성", "execution_mode": "backtest"},
        cookies=auth_cookies,
    ).json()
    client.post(f"/api/v1/strategies/{second['id']}/activate", cookies=auth_cookies)

    response = client.get("/api/v1/strategies", params={"status": "active"}, cookies=auth_cookies)

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == second["id"]
