"""Owner bootstrap endpoint — thin router (SoT B2, A3/A5.1).

``router -> service -> adapter/domain``: the only DB/hashing work happens in
``src.services.auth.bootstrap_owner``; this module just wires the request to
it and returns the domain-layer response schema unwrapped (SoT B4.4 — no
envelope on success).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from src.api.deps import get_signup_enabled, get_user_repository
from src.domain.user import UserRead, UserRepository
from src.services.auth import bootstrap_owner

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class BootstrapRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/bootstrap", status_code=201)
async def bootstrap(
    payload: BootstrapRequest,
    repo: Annotated[UserRepository, Depends(get_user_repository)],
    signup_enabled: Annotated[bool, Depends(get_signup_enabled)],
) -> UserRead:
    user = await bootstrap_owner(
        repo,
        signup_enabled=signup_enabled,
        email=payload.email,
        password=payload.password,
    )
    return UserRead.from_user(user)
