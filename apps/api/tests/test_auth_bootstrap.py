"""POST /api/v1/auth/bootstrap — success, signup-disabled, and duplicate-owner cases.

No DB container in this environment: ``get_user_repository`` and
``get_signup_enabled`` (src/api/deps.py) are overridden via
``app.dependency_overrides`` with ``conftest.FakeUserRepository``, the same
isolation approach ``FakeLLMClient`` (src/adapters/llm.py) establishes for
external adapters generally.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from src.api.deps import get_signup_enabled, get_user_repository
from src.main import app

from .conftest import FakeUserRepository

_PAYLOAD = {"email": "owner@example.com", "password": "correct horse battery staple"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def _stub_signup_enabled(enabled: bool) -> Callable[[], bool]:
    def _get() -> bool:
        return enabled

    return _get


def test_bootstrap_rejected_when_signup_disabled(client: TestClient) -> None:
    app.dependency_overrides[get_signup_enabled] = _stub_signup_enabled(False)
    app.dependency_overrides[get_user_repository] = FakeUserRepository

    response = client.post("/api/v1/auth/bootstrap", json=_PAYLOAD)

    assert response.status_code == 403
    assert response.json()["code"] == "SIGNUP_DISABLED"


def test_bootstrap_creates_owner_with_hashed_password(client: TestClient) -> None:
    repo = FakeUserRepository()
    app.dependency_overrides[get_signup_enabled] = _stub_signup_enabled(True)
    app.dependency_overrides[get_user_repository] = lambda: repo

    response = client.post("/api/v1/auth/bootstrap", json=_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == _PAYLOAD["email"]
    assert body["id"].startswith("usr_")
    assert "password" not in body
    assert "password_hash" not in body

    stored = repo.users[0]
    assert stored.password_hash.startswith("$argon2id$")
    assert stored.password_hash != _PAYLOAD["password"]


def test_bootstrap_rejects_second_request_once_owner_exists(client: TestClient) -> None:
    repo = FakeUserRepository()
    app.dependency_overrides[get_signup_enabled] = _stub_signup_enabled(True)
    app.dependency_overrides[get_user_repository] = lambda: repo

    first = client.post("/api/v1/auth/bootstrap", json=_PAYLOAD)
    second = client.post("/api/v1/auth/bootstrap", json=_PAYLOAD)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "OWNER_ALREADY_EXISTS"
    assert len(repo.users) == 1
