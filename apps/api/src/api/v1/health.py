"""Liveness endpoint.

Thin router per SoT B2 (``router → service → adapter/domain``). No service
call is needed yet since this is liveness-only; DB/Redis readiness checks are
out of scope for this issue and will route through a service once those
adapters exist.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def get_health() -> dict[str, str]:
    return {"status": "ok"}
