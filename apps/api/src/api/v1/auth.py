"""Owner bootstrap + login/logout/me endpoints — thin routers (SoT B2, A3/A5.1).

``router -> service -> adapter/domain``: the only DB/hashing/token work
happens in ``src.services.auth``; this module wires requests to it, sets/
clears the httpOnly auth cookies (``src.api.cookies``), and returns
domain-layer response schemas unwrapped (SoT B4.4 — no envelope on success).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr

from src.api.cookies import clear_auth_cookies, set_auth_cookies
from src.api.deps import (
    get_cookie_secure,
    get_current_user,
    get_secret_key,
    get_signup_enabled,
    get_user_repository,
)
from src.domain.user import User, UserRead, UserRepository
from src.services.auth import bootstrap_owner
from src.services.auth import login as login_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class BootstrapRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
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


@router.post("/login")
async def login(
    payload: LoginRequest,
    response: Response,
    repo: Annotated[UserRepository, Depends(get_user_repository)],
    secret_key: Annotated[str, Depends(get_secret_key)],
    cookie_secure: Annotated[bool, Depends(get_cookie_secure)],
) -> UserRead:
    user, tokens = await login_user(
        repo, email=payload.email, password=payload.password, secret_key=secret_key
    )
    set_auth_cookies(response, tokens, secure=cookie_secure)
    return UserRead.from_user(user)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    cookie_secure: Annotated[bool, Depends(get_cookie_secure)],
) -> None:
    clear_auth_cookies(response, secure=cookie_secure)


@router.get("/me")
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserRead:
    return UserRead.from_user(current_user)
