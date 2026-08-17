"""Glossary term YAML loader (SoT A6.12 — adapters).

The only adapter in this codebase backed by a static file rather than a DB
or network call — imports only ``src.domain`` per the layer contract.
``GLOSSARY_PATH`` is a fixed module constant, not sourced from
``src.config.Settings`` (SoT A6.12: no new env var for this feature), so
``src.api.deps`` can call ``load_glossary_terms(GLOSSARY_PATH)`` directly.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.domain.glossary import GlossaryTerm

# apps/api/src/adapters/glossary.py -> apps/api/glossary.ko.yaml
GLOSSARY_PATH = Path(__file__).resolve().parent.parent.parent / "glossary.ko.yaml"


def load_glossary_terms(path: Path) -> list[GlossaryTerm]:
    """Parse and validate the glossary YAML at ``path``.

    Raises ``ValueError`` on a duplicate ``key`` or a ``related`` reference
    to a key that doesn't exist — broken content fails fast at load time
    (process startup / test collection) rather than surfacing as a broken
    link in the UI.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    terms = [GlossaryTerm.model_validate(item) for item in raw]

    seen_keys: set[str] = set()
    for term in terms:
        if term.key in seen_keys:
            raise ValueError(f"Duplicate glossary key: {term.key}")
        seen_keys.add(term.key)

    for term in terms:
        for related_key in term.related:
            if related_key not in seen_keys:
                raise ValueError(
                    f"Glossary term '{term.key}' references unknown related "
                    f"key '{related_key}'"
                )

    return terms
