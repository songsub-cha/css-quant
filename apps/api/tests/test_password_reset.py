"""POST /password-reset/request + /password-reset/confirm (SoT A5.1).

No DB container in this environment: ``get_user_repository``,
``get_password_reset_token_repository``, and ``get_email_sender``
(src/api/deps.py) are overridden via ``app.dependency_overrides`` with
``conftest.FakeUserRepository``/``conftest.FakePasswordResetTokenRepository``/
``FakeEmailSender`` (src/adapters/email.py) — the same isolation approach
test_auth_bootstrap.py/test_auth_login.py establish.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.adapters.email import FakeEmailSender
from src.api.deps import (
    get_email_sender,
    get_password_reset_token_repository,
    get_user_repository,
)
from src.domain.ids import generate_uuid7
from src.domain.password_reset import PasswordResetToken, hash_reset_token
from src.domain.security import hash_password, verify_password
from src.domain.user import User
from src.main import app

from .conftest import FakePasswordResetTokenRepository, FakeUserRepository

_EMAIL = "owner@example.com"
_PASSWORD = "correct horse battery staple"
_NEW_PASSWORD = "new correct horse battery staple"


def _make_token(user_id: UUID, raw_token: str, *, expires_at: datetime) -> PasswordResetToken:
    return PasswordResetToken(
        id=generate_uuid7(),
        user_id=user_id,
        token_hash=hash_reset_token(raw_token),
        expires_at=expires_at,
        used_at=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def user_repo() -> FakeUserRepository:
    repo = FakeUserRepository()
    now = datetime.now(UTC)
    repo.users.append(
        User(
            id=generate_uuid7(),
            email=_EMAIL,
            password_hash=hash_password(_PASSWORD),
            created_at=now,
            updated_at=now,
        )
    )
    return repo


@pytest.fixture
def token_repo() -> FakePasswordResetTokenRepository:
    return FakePasswordResetTokenRepository()


@pytest.fixture
def email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def client(
    user_repo: FakeUserRepository,
    token_repo: FakePasswordResetTokenRepository,
    email_sender: FakeEmailSender,
) -> Iterator[TestClient]:
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_password_reset_token_repository] = lambda: token_repo
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_request_with_existing_email_returns_200_and_sends_email(
    client: TestClient,
    email_sender: FakeEmailSender,
    token_repo: FakePasswordResetTokenRepository,
) -> None:
    response = client.post("/api/v1/auth/password-reset/request", json={"email": _EMAIL})

    assert response.status_code == 200
    assert len(email_sender.sent) == 1
    assert email_sender.sent[0].to == _EMAIL
    assert len(token_repo.tokens) == 1


def test_request_with_unknown_email_returns_200_and_sends_no_email(
    client: TestClient,
    email_sender: FakeEmailSender,
    token_repo: FakePasswordResetTokenRepository,
) -> None:
    response = client.post(
        "/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 200
    assert email_sender.sent == []
    assert token_repo.tokens == []


def test_confirm_with_valid_token_updates_password_and_returns_204(
    client: TestClient,
    user_repo: FakeUserRepository,
    token_repo: FakePasswordResetTokenRepository,
) -> None:
    user = user_repo.users[0]
    raw_token = "a-raw-reset-token"
    token_repo.tokens.append(
        _make_token(user.id, raw_token, expires_at=datetime.now(UTC) + timedelta(minutes=30))
    )

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": _NEW_PASSWORD},
    )

    assert response.status_code == 204
    assert verify_password(_NEW_PASSWORD, user.password_hash)
    assert not verify_password(_PASSWORD, user.password_hash)


def test_confirm_with_expired_token_returns_invalid_reset_token(
    client: TestClient,
    user_repo: FakeUserRepository,
    token_repo: FakePasswordResetTokenRepository,
) -> None:
    user = user_repo.users[0]
    raw_token = "expired-token"
    token_repo.tokens.append(
        _make_token(user.id, raw_token, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": _NEW_PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_RESET_TOKEN"


def test_confirm_with_unknown_token_returns_invalid_reset_token(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "does-not-exist", "new_password": _NEW_PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_RESET_TOKEN"


def test_confirm_token_cannot_be_reused(
    client: TestClient,
    user_repo: FakeUserRepository,
    token_repo: FakePasswordResetTokenRepository,
) -> None:
    user = user_repo.users[0]
    raw_token = "single-use-token"
    token_repo.tokens.append(
        _make_token(user.id, raw_token, expires_at=datetime.now(UTC) + timedelta(minutes=30))
    )

    first = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": _NEW_PASSWORD},
    )
    second = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "another-new-password"},
    )

    assert first.status_code == 204
    assert second.status_code == 400
    assert second.json()["code"] == "INVALID_RESET_TOKEN"
