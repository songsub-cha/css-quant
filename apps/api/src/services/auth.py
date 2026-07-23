"""Owner bootstrap orchestration (SoT B2 — services layer, A3/A5.1).

Single-user system: "signup" is the one-time owner bootstrap, gated by
``SIGNUP_ENABLED`` (SoT D2) and by there being no existing user at all.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from src.domain.security import hash_password
from src.domain.user import User, UserRepository
from src.errors import ApiError, ErrorCode

_OWNER_ALREADY_EXISTS_DETAIL = "An owner account already exists; this is a single-user system."


async def bootstrap_owner(
    repo: UserRepository, *, signup_enabled: bool, email: str, password: str
) -> User:
    if not signup_enabled:
        raise ApiError(
            status=403,
            code=ErrorCode.SIGNUP_DISABLED,
            detail="Signup is disabled. Set SIGNUP_ENABLED=true for the one-time owner bootstrap.",
        )
    if await repo.exists_any():
        raise ApiError(
            status=409, code=ErrorCode.OWNER_ALREADY_EXISTS, detail=_OWNER_ALREADY_EXISTS_DETAIL
        )

    try:
        return await repo.create(email=email, password_hash=hash_password(password))
    except IntegrityError as exc:
        # TOCTOU: another request created the owner between the exists_any()
        # check above and this commit. The DB's unique constraint on email
        # is the real guard; this just translates it to the same 409.
        raise ApiError(
            status=409, code=ErrorCode.OWNER_ALREADY_EXISTS, detail=_OWNER_ALREADY_EXISTS_DETAIL
        ) from exc
