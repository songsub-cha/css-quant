from __future__ import annotations

from uuid import UUID

from src.domain.ids import format_prefixed_id, generate_uuid7


def test_generate_uuid7_returns_version_7_uuid() -> None:
    value = generate_uuid7()

    assert isinstance(value, UUID)
    assert value.version == 7


def test_generate_uuid7_is_unique_per_call() -> None:
    assert generate_uuid7() != generate_uuid7()


def test_format_prefixed_id_joins_prefix_and_uuid_with_underscore() -> None:
    value = generate_uuid7()

    assert format_prefixed_id("usr", value) == f"usr_{value}"


def test_format_prefixed_id_is_reusable_across_entity_prefixes() -> None:
    value = generate_uuid7()

    assert format_prefixed_id("str", value) == f"str_{value}"
    assert format_prefixed_id("bt", value) == f"bt_{value}"
