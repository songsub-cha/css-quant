"""Test-collection env scaffolding + shared fakes.

``Settings.cookie_secure`` (SoT D2) has no default on purpose — every
deployment must set it explicitly. But two modules build a module-level
``Settings()`` at *import* time: ``src/workers/settings.py`` (imported by
``tests/test_worker_settings.py``) and ``alembic/env.py``. Without
``COOKIE_SECURE`` present in the environment before those imports happen,
pytest collection itself fails with a ``ValidationError`` before any test
runs. ``secret_key`` (added for JWT issuance, SoT D2/B4.6) has the same
import-time-required shape, plus a ``min_length=32`` floor — the dummy value
below satisfies it.

pytest imports ``conftest.py`` ahead of collecting test modules in the same
directory tree, so setting the env vars here (rather than in a fixture,
which would run too late) is what makes collection succeed. This is
test-process scaffolding only — real deployments must still set these
explicitly via ``.env`` (dev/prod compose ``env_file``); nothing here
weakens that requirement.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

from src.domain.ids import generate_uuid7
from src.domain.user import User

os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-for-prod-use-000")


class FakeUserRepository:
    """In-memory ``UserRepository`` (SoT domain protocol) — no DB container in this environment.

    Shared by every auth test module (bootstrap, login, ``get_current_user``)
    the same way ``FakeLLMClient`` (src/adapters/llm.py) stands in for a real
    external adapter.
    """

    def __init__(self) -> None:
        self.users: list[User] = []

    async def exists_any(self) -> bool:
        return bool(self.users)

    async def create(self, *, email: str, password_hash: str) -> User:
        now = datetime.now(UTC)
        user = User(
            id=generate_uuid7(),
            email=email,
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        )
        self.users.append(user)
        return user

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.users if u.email == email), None)

    async def get_by_id(self, user_id: UUID) -> User | None:
        return next((u for u in self.users if u.id == user_id), None)
