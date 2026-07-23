"""RFC 7807 problem+json error format (SoT B4.4).

Leaf module outside the six layered packages SoT B2 orders — same role as
``src/config.py`` (see its docstring): every layer (domain, adapters,
services, api/v1, engine, workers) is free to import this, and it imports
nothing from them, so no import-linter contract needs to reference it.

Only the error codes this issue's scope needs are defined here; later
issues add more members to ``ErrorCode`` as new failure cases arise.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    OWNER_ALREADY_EXISTS = "OWNER_ALREADY_EXISTS"
    SIGNUP_DISABLED = "SIGNUP_DISABLED"


class ApiError(Exception):
    """Raised by services, translated to an RFC 7807 response below."""

    def __init__(self, *, status: int, code: ErrorCode, detail: str) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        super().__init__(detail)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": exc.code.value.replace("_", " ").title(),
                "status": exc.status,
                "detail": exc.detail,
                "code": exc.code.value,
            },
        )
