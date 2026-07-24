"""Owner bootstrap orchestration (SoT B2 — services layer, A3/A5.1).

Single-user system: "signup" is the one-time owner bootstrap, gated by
``SIGNUP_ENABLED`` (SoT D2) and by there being no existing user at all.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from src.domain.security import hash_password, verify_password
from src.domain.tokens import TokenPair, create_token_pair
from src.domain.user import User, UserRepository
from src.errors import ApiError, ErrorCode

_OWNER_ALREADY_EXISTS_DETAIL = "An owner account already exists; this is a single-user system."
_INVALID_CREDENTIALS_DETAIL = "Invalid email or password."

# Hashed once at import time so a lookup miss still pays argon2id's cost —
# without this, "unknown email" would return measurably faster than "known
# email, wrong password", letting response timing enumerate registered
# accounts. The plaintext behind this hash is never accepted as a real
# password since it isn't tied to any user record.
_DUMMY_PASSWORD_HASH = hash_password("timing-parity-dummy-password")


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


async def login(
    repo: UserRepository, *, email: str, password: str, secret_key: str
) -> tuple[User, TokenPair]:
    user = await repo.get_by_email(email)
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH

    # verify_password always runs (it's the left operand of `or`), even when
    # user is None, so a nonexistent-email request costs the same as a
    # wrong-password one. `user is None` is still checked explicitly: it's
    # the only thing that can reject a request where verify_password somehow
    # returned True against the dummy hash (SoT B4.5 — never trust a lookup
    # miss to fail on its own).
    if not verify_password(password, password_hash) or user is None:
        raise ApiError(
            status=401, code=ErrorCode.INVALID_CREDENTIALS, detail=_INVALID_CREDENTIALS_DETAIL
        )

    return user, create_token_pair(user.id, secret_key=secret_key)
