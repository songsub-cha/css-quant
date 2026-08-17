"""UUID v7 primary keys + prefixed external IDs (SoT B4.1).

Python 3.12's stdlib ``uuid`` module has no v7 support (that lands in
3.14), so the ``uuid6`` backport fills the gap. ``format_prefixed_id``
takes the prefix as a parameter so every external-ID prefix in SoT B4.1
(``usr_``, ``str_``, ``bt_``, ``ord_``, ``oc_``, ``pf_``) can reuse it.

``parse_prefixed_id`` is its inverse — the codebase's first caller that
needs to turn a path/body-supplied prefixed string (e.g. ``ast_...``) back
into a ``UUID`` (``src/api/v1/watchlist.py``, SoT A5.2). It raises
``ValueError`` on a missing/mismatched prefix or a malformed UUID tail;
FastAPI/Pydantic turn that into a 422 when called from a request
validator, matching every other request-shape error in this codebase.
"""

from __future__ import annotations

from uuid import UUID

from uuid6 import uuid7


def generate_uuid7() -> UUID:
    return uuid7()


def format_prefixed_id(prefix: str, value: UUID) -> str:
    return f"{prefix}_{value}"


def parse_prefixed_id(prefix: str, value: str) -> UUID:
    expected_prefix = f"{prefix}_"
    if not value.startswith(expected_prefix):
        raise ValueError(f"expected an id prefixed with {expected_prefix!r}, got {value!r}")
    return UUID(value[len(expected_prefix) :])
