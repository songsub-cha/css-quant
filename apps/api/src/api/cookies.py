"""Auth cookie helpers — shared by the login/logout routes and ``get_current_user``.

Pulled out of ``api/v1/auth.py`` because both the router (setting cookies on
login, clearing them on logout) and ``api/deps.get_current_user`` (reading
the access cookie) need the same cookie names. Names follow SoT B5.7's
already-settled refresh cookie name (``rt``); ``at`` mirrors it for access.
Takes ``secure`` as a plain parameter rather than importing ``src.config``,
keeping this module a leaf the same way ``adapters/db.py`` takes
``database_url`` as a parameter (see ``src/config.py`` docstring).
"""

from __future__ import annotations

from fastapi import Response

from src.domain.tokens import ACCESS_TOKEN_TTL, REFRESH_TOKEN_TTL, TokenPair

ACCESS_TOKEN_COOKIE = "at"
REFRESH_TOKEN_COOKIE = "rt"


def set_auth_cookies(response: Response, tokens: TokenPair, *, secure: bool) -> None:
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        tokens.access_token,
        max_age=int(ACCESS_TOKEN_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        tokens.refresh_token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_auth_cookies(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        ACCESS_TOKEN_COOKIE, path="/", httponly=True, samesite="lax", secure=secure
    )
    response.delete_cookie(
        REFRESH_TOKEN_COOKIE, path="/", httponly=True, samesite="lax", secure=secure
    )
