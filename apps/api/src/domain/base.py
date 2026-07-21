"""Declarative base for ORM models (SoT B2 — domain layer, pure).

Domain models added in later issues subclass ``Base``. This module has no
columns and imports nothing beyond SQLAlchemy itself, so it keeps the
domain layer's "no other-layer imports" rule intact.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
