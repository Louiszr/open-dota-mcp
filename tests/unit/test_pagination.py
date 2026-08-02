from __future__ import annotations

import pytest

from open_dota_mcp.pagination import PaginationError, SnapshotRegistry


def test_page_bounds_and_canonical_fingerprint() -> None:
    registry = SnapshotRegistry()
    assert registry.fingerprint({"b": 2, "a": 1}) == registry.fingerprint({"a": 1, "b": 2})
    for invalid in (0, 101):
        with pytest.raises(PaginationError, match="between"):
            registry.first_page(tool="x", query={}, items=[], page_size=invalid)


def test_snapshot_traversal_rotates_tokens_without_repeat_or_skip() -> None:
    tokens = iter(["first", "second", "third"])
    registry = SnapshotRegistry(token_factory=lambda: next(tokens))
    first, meta = registry.first_page(
        tool="x", query={"id": 1}, items=list(range(205)), page_size=100
    )
    assert first == list(range(100))
    assert meta.continuation_token == "first"
    second, meta2 = registry.next_page("first", tool="x", query={"id": 1})
    final, meta3 = registry.next_page("second", tool="x", query={"id": 1})
    assert second + final == list(range(100, 205))
    assert meta2.continuation_token == "second"
    assert meta3.terminal is True
    with pytest.raises(PaginationError, match="replayed"):
        registry.next_page("first", tool="x")


def test_snapshot_is_immutable_and_rejects_mismatch_cross_tool() -> None:
    source = [1, 2, 3]
    registry = SnapshotRegistry(token_factory=lambda: "opaque")
    first, meta = registry.first_page(tool="one", query={"id": 1}, items=source, page_size=1)
    source.insert(0, 0)
    assert first == [1]
    with pytest.raises(PaginationError, match="another tool"):
        registry.next_page(str(meta.continuation_token), tool="two")
    with pytest.raises(PaginationError, match="do not match"):
        registry.next_page(str(meta.continuation_token), tool="one", query={"id": 2})


def test_expiry_and_lru_eviction_are_actionable() -> None:
    now = {"value": 0.0}
    sequence = iter(["one", "two", "three"])
    registry = SnapshotRegistry(
        ttl_seconds=10,
        capacity=1,
        clock=lambda: now["value"],
        token_factory=lambda: next(sequence),
    )
    _, first = registry.first_page(tool="x", query={"id": 1}, items=[1, 2], page_size=1)
    registry.first_page(tool="x", query={"id": 2}, items=[1, 2], page_size=1)
    with pytest.raises(PaginationError) as evicted:
        registry.next_page(str(first.continuation_token), tool="x")
    assert evicted.value.restart_required is True
    now["value"] = 20
    with pytest.raises(PaginationError) as expired:
        registry.next_page("two", tool="x")
    assert expired.value.code == "continuation_expired"


def test_defaults_match_contract() -> None:
    registry = SnapshotRegistry()
    assert registry.ttl_seconds == 1800
    assert registry.capacity == 32


def test_replacement_registry_invalidates_tokens_and_default_capacity_is_lru() -> None:
    sequence = (f"token-{value}" for value in range(40))
    registry = SnapshotRegistry(capacity=32, token_factory=lambda: next(sequence))
    tokens: list[str] = []
    for value in range(33):
        _, metadata = registry.first_page(
            tool="x", query={"id": value}, items=[value, value + 1], page_size=1
        )
        tokens.append(str(metadata.continuation_token))
    with pytest.raises(PaginationError) as evicted:
        registry.next_page(tokens[0], tool="x")
    assert evicted.value.restart_required
    replacement = SnapshotRegistry()
    with pytest.raises(PaginationError) as missing:
        replacement.next_page(tokens[-1], tool="x")
    assert missing.value.code == "invalid_continuation"


def test_snapshot_context_is_retained_across_rotating_pages() -> None:
    tokens = iter(["first", "second"])
    registry = SnapshotRegistry(token_factory=lambda: next(tokens))
    _, first = registry.first_page(
        tool="analysis",
        query={"team_id": 1},
        items=[1, 2, 3],
        page_size=1,
        context={"coverage": {"examined": 3}},
    )
    page, second, context = registry.next_page_with_context(
        str(first.continuation_token), tool="analysis"
    )
    assert page == [2]
    assert second.continuation_token == "second"
    assert context == {"coverage": {"examined": 3}}
