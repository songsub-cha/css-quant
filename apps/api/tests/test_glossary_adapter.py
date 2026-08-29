"""Glossary YAML loader tests (SoT A6.12).

``test_real_glossary_file_*`` load the actual ``apps/api/glossary.ko.yaml``
and act as a content lint (schema/uniqueness/link-integrity/count), so a
broken or incomplete glossary entry fails CI rather than surfacing as a
broken link in the UI. ``test_load_glossary_terms_rejects_*`` exercise the
loader's validation against small on-disk fixtures.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from src.adapters.glossary import GLOSSARY_PATH, load_glossary_terms
from src.domain.glossary import GlossaryCategory, GlossaryTerm


@pytest.fixture(scope="module")
def real_terms() -> list[GlossaryTerm]:
    return load_glossary_terms(GLOSSARY_PATH)


def test_real_glossary_file_parses_without_error(real_terms: list[GlossaryTerm]) -> None:
    assert all(isinstance(term, GlossaryTerm) for term in real_terms)


def test_real_glossary_file_has_60_to_80_entries(real_terms: list[GlossaryTerm]) -> None:
    assert 60 <= len(real_terms) <= 80


def test_real_glossary_file_has_unique_keys(real_terms: list[GlossaryTerm]) -> None:
    keys = [term.key for term in real_terms]
    assert len(keys) == len(set(keys))


def test_real_glossary_file_related_links_resolve(real_terms: list[GlossaryTerm]) -> None:
    known_keys = {term.key for term in real_terms}
    for term in real_terms:
        for related_key in term.related:
            assert related_key in known_keys, (
                f"{term.key} references unknown related key {related_key}"
            )


def test_real_glossary_file_covers_all_seven_categories(real_terms: list[GlossaryTerm]) -> None:
    covered = {term.category for term in real_terms}
    assert covered == set(GlossaryCategory)


_VALID_ENTRY = """
- key: per
  term_ko: "PER"
  term_en: "PER"
  category: financial_metric
  definition: "d"
  interpretation: "i"
"""


@pytest.fixture
def tmp_yaml_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "glossary.ko.yaml"
    yield path


def test_load_glossary_terms_parses_valid_fixture(tmp_yaml_path: Path) -> None:
    tmp_yaml_path.write_text(_VALID_ENTRY, encoding="utf-8")

    terms = load_glossary_terms(tmp_yaml_path)

    assert len(terms) == 1
    assert terms[0].key == "per"
    assert terms[0].category == GlossaryCategory.FINANCIAL_METRIC


def test_load_glossary_terms_rejects_duplicate_key(tmp_yaml_path: Path) -> None:
    tmp_yaml_path.write_text(_VALID_ENTRY + _VALID_ENTRY, encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate glossary key"):
        load_glossary_terms(tmp_yaml_path)


def test_load_glossary_terms_rejects_unknown_related_key(tmp_yaml_path: Path) -> None:
    tmp_yaml_path.write_text(
        _VALID_ENTRY.rstrip() + "\n  related: [does_not_exist]\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unknown related"):
        load_glossary_terms(tmp_yaml_path)
