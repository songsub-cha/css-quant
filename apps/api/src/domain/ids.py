"""UUID v7 primary keys + prefixed external IDs (SoT B4.1).

Python 3.12's stdlib ``uuid`` module has no v7 support (that lands in
3.14), so the ``uuid6`` backport fills the gap. ``format_prefixed_id``
takes the prefix as a parameter so every external-ID prefix in SoT B4.1
(``usr_``, ``str_``, ``bt_``, ``ord_``, ``oc_``, ``pf_``) can reuse it.
"""

from __future__ import annotations

from uuid import UUID

from uuid6 import uuid7


def generate_uuid7() -> UUID:
    return uuid7()


def format_prefixed_id(prefix: str, value: UUID) -> str:
    return f"{prefix}_{value}"
