"""POST /login, POST /logout, GET /me — cookie issuance and protected-route behavior.

``TestClient``'s cookie jar normalizes away HttpOnly/SameSite/Max-Age (it
only tracks name/value for replay), so cookie *attributes* are asserted by
parsing the raw ``set-cookie`` response headers instead — the same
information a browser would use to decide whether to accept/send the
cookie.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from src.api.deps import get_cookie_secure, get_secret_key, get_user_repository
from src.domain.ids import generate_uuid7
from src.domain.security import hash_password
from src.domain.tokens import TokenType, create_access_token, create_refresh_token
from src.domain.user import User
from src.main import app

from .conftest import FakeUserRepository

_SECRET_KEY = "login-test-secret-key-at-least-32-characters"
_EMAIL = "owner@example.com"
_PASSWORD = "correct horse battery staple"


@pytest.fixture
def repo() -> FakeUserRepository:
    # created_at/updated_at set explicitly, same as
    # FakeUserRepository.create() — both columns are server_default in the
    # real schema, so a bare User(...) construction leaves them None, which
    # UserRead.from_user() (a required datetime field) would reject.
    fake = FakeUserRepository()
    now = datetime.now(UTC)
    fake.users.append(
        User(
            id=generate_uuid7(),
            email=_EMAIL,
            password_hash=hash_password(_PASSWORD),
            created_at=now,
            updated_at=now,
        )
    )
    return fake


@pytest.fixture
def client(repo: FakeUserRepository) -> Iterator[TestClient]:
    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_secret_key] = lambda: _SECRET_KEY
    app.dependency_overrides[get_cookie_secure] = lambda: True
    yield TestClient(app)
    app.dependency_overrides.clear()


def _cookie_header(response: Response, name: str) -> str:
    headers = response.headers.get_list("set-cookie")
    return next(h for h in headers if h.startswith(f"{name}="))


def test_login_success_sets_auth_cookies(client: TestClient, repo: FakeUserRepository) -> None:
    response = client.post("/api/v1/auth/login", json={"email": _EMAIL, "password": _PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == _EMAIL
    assert body["id"] == f"usr_{repo.users[0].id}"
    assert "password" not in body
    assert "password_hash" not in body
    assert _PASSWORD not in response.text

    access_cookie = _cookie_header(response, "at")
    assert "HttpOnly" in access_cookie
    assert "samesite=lax" in access_cookie.lower()
    assert "Max-Age=900" in access_cookie
    assert "Secure" in access_cookie

    refresh_cookie = _cookie_header(response, "rt")
    assert "HttpOnly" in refresh_cookie
    assert "samesite=lax" in refresh_cookie.lower()
    assert "Max-Age=2592000" in refresh_cookie
    assert "Secure" in refresh_cookie


def test_login_wrong_password_returns_401(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": _EMAIL, "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert "set-cookie" not in response.headers


def test_login_unknown_email_returns_same_error_as_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": _PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_logout_clears_auth_cookies(client: TestClient) -> None:
    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert "Max-Age=0" in _cookie_header(response, "at")
    assert "Max-Age=0" in _cookie_header(response, "rt")


def test_me_without_cookie_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_me_with_valid_access_token_returns_user(
    client: TestClient, repo: FakeUserRepository
) -> None:
    user = repo.users[0]
    token = create_access_token(user.id, secret_key=_SECRET_KEY)

    response = client.get("/api/v1/auth/me", cookies={"at": token})

    assert response.status_code == 200
    assert response.json()["email"] == _EMAIL


def test_me_with_expired_access_token_returns_401(
    client: TestClient, repo: FakeUserRepository
) -> None:
    user = repo.users[0]
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": str(user.id),
            "type": TokenType.ACCESS.value,
            "iat": now - timedelta(minutes=30),
            "exp": now - timedelta(minutes=15),
        },
        _SECRET_KEY,
        algorithm="HS256",
    )

    response = client.get("/api/v1/auth/me", cookies={"at": expired})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_me_with_refresh_token_in_access_cookie_returns_401(
    client: TestClient, repo: FakeUserRepository
) -> None:
    # Type confusion guard: a refresh token must not be accepted where an
    # access token is expected, even with a valid signature.
    user = repo.users[0]
    refresh_token = create_refresh_token(user.id, secret_key=_SECRET_KEY)

    response = client.get("/api/v1/auth/me", cookies={"at": refresh_token})

    assert response.status_code == 401
