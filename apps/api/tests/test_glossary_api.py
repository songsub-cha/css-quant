"""GET /api/v1/glossary(/{key}) — router-level tests (SoT A6.12).

``TestClient`` + ``app.dependency_overrides``, same pattern as
``test_watchlist_api.py``: no DB container in this environment, so
``get_user_repository``/``get_secret_key`` are swapped for fakes, and
``get_glossary_terms`` (normally an ``@lru_cache``'d YAML load) is
overridden with a fixed fixture list.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.api.deps import get_glossary_terms, get_secret_key, get_user_repository
from src.domain.glossary import GlossaryCategory, GlossaryTerm
from src.domain.ids import generate_uuid7
from src.domain.security import hash_password
from src.domain.tokens import create_access_token
from src.domain.user import User
from src.main import app

from .conftest import FakeUserRepository

_SECRET_KEY = "glossary-api-test-secret-key-at-least-32-chars"

_PER = GlossaryTerm(
    key="per",
    term_ko="PER",
    term_en="Price-to-Earnings Ratio",
    category=GlossaryCategory.FINANCIAL_METRIC,
    definition="주가를 주당순이익으로 나눈 값.",
    interpretation="낮을수록 저평가.",
)
_MOMENTUM = GlossaryTerm(
    key="momentum_factor",
    term_ko="모멘텀 팩터",
    term_en="Momentum Factor",
    category=GlossaryCategory.FACTOR,
    definition="상승 추세를 측정하는 지표.",
    interpretation="높을수록 상승세가 강함.",
)
_FIXTURE_TERMS = [_PER, _MOMENTUM]


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
def client(user_repo: FakeUserRepository) -> Iterator[TestClient]:
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_secret_key] = lambda: _SECRET_KEY
    app.dependency_overrides[get_glossary_terms] = lambda: _FIXTURE_TERMS
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth_cookies(user_repo: FakeUserRepository) -> dict[str, str]:
    token = create_access_token(user_repo.users[0].id, secret_key=_SECRET_KEY)
    return {"at": token}


def test_endpoints_without_auth_cookie_return_401(client: TestClient) -> None:
    assert client.get("/api/v1/glossary").status_code == 401
    assert client.get("/api/v1/glossary/per").status_code == 401


def test_list_terms_returns_unwrapped_array(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.get("/api/v1/glossary", cookies=auth_cookies)

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert {item["key"] for item in body} == {"per", "momentum_factor"}


def test_list_terms_filters_by_category(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.get(
        "/api/v1/glossary", params={"category": "factor"}, cookies=auth_cookies
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["key"] == "momentum_factor"


def test_list_terms_filters_by_q(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.get("/api/v1/glossary", params={"q": "PER"}, cookies=auth_cookies)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["key"] == "per"


def test_get_term_returns_single_item(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.get("/api/v1/glossary/per", cookies=auth_cookies)

    assert response.status_code == 200
    assert response.json()["key"] == "per"


def test_get_term_with_unknown_key_returns_404(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.get("/api/v1/glossary/does_not_exist", cookies=auth_cookies)

    assert response.status_code == 404
    assert response.json()["code"] == "GLOSSARY_TERM_NOT_FOUND"
