"""GET /api/v1/glossary(/{key}) — glossary term lookup endpoints (SoT A6.12, thin router).

``router -> service -> adapter/domain`` (SoT B2), same shape as
``api/v1/watchlist.py``: filtering happens in ``src.services.glossary``,
loading/caching happens in ``src.api.deps.get_glossary_terms``; this module
only wires the request, requires auth (same as every other protected
endpoint — single-user app, no unauthenticated surface), and shapes the
response.

``GET /api/v1/glossary`` returns an unwrapped array (SoT B4.4's default
rule) — the term count is fixed and small (~76), so cursor pagination
isn't needed (same interpretation as #66/#67: cursor is the *mechanism*
when pagination is needed, not a blanket requirement for every list).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_current_user, get_glossary_terms
from src.domain.glossary import GlossaryCategory, GlossaryTerm
from src.domain.user import User
from src.errors import ApiError, ErrorCode
from src.services.glossary import list_glossary_terms

router = APIRouter(prefix="/api/v1/glossary", tags=["glossary"])


@router.get("")
async def list_terms(
    current_user: Annotated[User, Depends(get_current_user)],
    terms: Annotated[list[GlossaryTerm], Depends(get_glossary_terms)],
    category: Annotated[GlossaryCategory | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> list[GlossaryTerm]:
    return list_glossary_terms(terms, category=category, q=q)


@router.get("/{key}")
async def get_term(
    key: str,
    current_user: Annotated[User, Depends(get_current_user)],
    terms: Annotated[list[GlossaryTerm], Depends(get_glossary_terms)],
) -> GlossaryTerm:
    for term in terms:
        if term.key == key:
            return term
    raise ApiError(
        status=404,
        code=ErrorCode.GLOSSARY_TERM_NOT_FOUND,
        detail="Glossary term not found.",
    )
