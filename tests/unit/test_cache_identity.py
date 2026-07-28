from __future__ import annotations

import pytest

from open_dota_mcp.cache.identity import build_identity


def test_identity_is_typed_reordered_and_excludes_only_api_key() -> None:
    first = build_identity(
        source="https://API.OpenDota.com:443/api/",
        operation="get_teams_page",
        query_inputs={"page": 4, "api_key": "secret", "future": "yes"},
    )
    second = build_identity(
        source="https://api.opendota.com/api",
        operation="get_teams_page",
        query_inputs={"future": "yes", "page": 4, "api_key": "different"},
    )
    assert first.digest == second.digest
    assert "secret" not in first.canonical_json + first.safe_description
    assert (
        build_identity(
            source="https://api.opendota.com/api",
            operation="get_teams_page",
            query_inputs={"page": "4", "future": "yes"},
        ).digest
        != first.digest
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_identity_rejects_ambiguous_values(value: object) -> None:
    with pytest.raises(ValueError):
        build_identity(
            source="https://api.opendota.com/api", operation="get", query_inputs={"x": value}
        )


def test_every_contract_component_and_unknown_query_changes_identity() -> None:
    base = dict(
        source="https://api.opendota.com/api",
        operation="get_team_matches",
        path_inputs={"team_id": 1},
        query_inputs={"future": "a"},
    )
    original = build_identity(**base)
    variants = [
        {**base, "source": "https://api.opendota.com/v2"},
        {**base, "operation": "get_team"},
        {**base, "path_inputs": {"team_id": 2}},
        {**base, "query_inputs": {"future": "b"}},
    ]
    assert all(build_identity(**variant).digest != original.digest for variant in variants)


def test_safe_description_is_bounded_and_omits_unreviewed_values() -> None:
    identity = build_identity(
        source="https://api.opendota.com/api",
        operation="get_match",
        path_inputs={"match_id": 123},
        query_inputs={"future_token": "credential-like-value", "api_key": "actual-secret"},
    )
    assert identity.safe_description == "get_match(match_id=123)"
    assert len(identity.safe_description) <= 200
    visible = identity.canonical_json + identity.safe_description
    assert "actual-secret" not in visible
    assert all(word not in visible for word in ["session", "package_version", "Authorization"])
