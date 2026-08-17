"""Glossary term search/category filter (SoT A6.12 — services).

Pure function, no I/O — ``src.api.deps.get_glossary_terms`` loads and
caches the term list once per process; this just filters an already-loaded
sequence.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.domain.glossary import GlossaryCategory, GlossaryTerm


def list_glossary_terms(
    terms: Sequence[GlossaryTerm],
    *,
    category: GlossaryCategory | None = None,
    q: str | None = None,
) -> list[GlossaryTerm]:
    result = list(terms)

    if category is not None:
        result = [term for term in result if term.category == category]

    if q is not None:
        needle = q.lower()
        result = [
            term
            for term in result
            if needle in term.key.lower()
            or needle in term.term_ko.lower()
            or needle in term.term_en.lower()
            or needle in term.definition.lower()
        ]

    return result
