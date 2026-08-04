from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from fastmcp import Client

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.errors import UpstreamError
from open_dota_mcp.server import create_server
from open_dota_mcp.services.fantasy import FantasyService


class FantasyContractClient:
    def __init__(self) -> None:
        self.match_calls = 0

    async def get_pro_players(self) -> list[dict[str, Any]]:
        return [
            {"account_id": 101, "name": "Example"},
            {"account_id": 102, "name": "Duplicate"},
            {"account_id": 103, "name": "Duplicate"},
        ]

    async def get_patches(self) -> list[dict[str, Any]]:
        return [
            {"id": 60, "name": "7.40", "date": 1751328000},
            {"id": 61, "name": "7.41", "date": 1782864000},
        ]

    async def get_leagues(self) -> list[dict[str, Any]]:
        return [{"leagueid": 10, "name": "TI 2026", "tier": "premium"}]

    async def get_heroes(self) -> list[dict[str, Any]]:
        return [{"id": 25, "localized_name": "Lina"}]

    async def get_player_matches(
        self, _account_id: int, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        if offset:
            return []
        return [
            {"match_id": 3, "start_time": 1783000003, "leagueid": 0},
            {"match_id": 2, "start_time": 1783000002, "leagueid": 10},
            {"match_id": 1, "start_time": 1783000001, "leagueid": 10},
        ][:limit]

    async def get_match(self, match_id: int) -> dict[str, Any]:
        self.match_calls += 1
        league_id = 0 if match_id == 3 else 10
        return {
            "match_id": match_id,
            "version": 21,
            "start_time": 1783000000 + match_id,
            "duration": 1800,
            "patch": 61,
            "leagueid": league_id,
            "league": {"name": "TI 2026", "tier": "premium"},
            "series_id": 501 if match_id == 2 else None,
            "radiant_team_id": 1,
            "dire_team_id": 2,
            "radiant_name": "Radiant Pro",
            "dire_name": "Dire Pro",
            "radiant_win": True,
            "radiant_score": 10,
            "dire_score": 5,
            "players": [
                {
                    "account_id": 101,
                    "player_slot": 0,
                    "hero_id": 25,
                    "kills": match_id,
                    "deaths": 1,
                    "assists": 4,
                    "last_hits": 100,
                    "denies": 5,
                    "gold_per_min": 500,
                    "tower_kills": 0,
                    "obs_placed": 0,
                    "camps_stacked": 0,
                    "rune_pickups": 0,
                    "item_uses": {"smoke_of_deceit": 0},
                    "roshans_killed": 0,
                    "stuns": 1.5,
                    "couriers_killed": 0,
                    "firstblood_claimed": 1 if match_id == 2 else 0,
                },
                {
                    "account_id": 201,
                    "player_slot": 128,
                    "firstblood_claimed": 0 if match_id == 2 else 1,
                },
            ],
            "objectives": [],
        }


async def invoke(
    arguments: dict[str, Any], fake: FantasyContractClient | None = None
) -> dict[str, Any]:
    runtime = fake or FantasyContractClient()
    async with Client(create_server(client=runtime)) as session:  # type: ignore[arg-type]
        result = await session.call_tool("get_pro_player_fantasy", arguments)
    return result.structured_content


@pytest.mark.asyncio
async def test_slim_default_professional_gate_scoring_and_empty() -> None:
    slim = await invoke({"account_id": 101, "tournament_tiers": ["all"]})
    assert [item["context"]["match_id"] for item in slim["matches"]] == [2, 1]
    assert slim["filters"]["patch"] == "7.41"
    assert slim["returned_count"] == 2
    assert [item["raw_stats"]["first_blood"] for item in slim["matches"]] == [True, False]
    assert "reference_uri" not in slim
    assert all("fantasy_scoring" not in item for item in slim["matches"])
    scored = await invoke({"account_id": 101, "match_count": 1, "include": ["fantasy_scoring"]})
    first_blood = next(
        emblem
        for emblem in scored["matches"][0]["fantasy_scoring"]["emblems"]
        if emblem["key"] == "first_blood"
    )
    assert first_blood["raw_points"] == 1934
    assert scored["reference_uri"] == "opendota://fantasy/ti-2026/scoring"
    assert len(scored["matches"][0]["fantasy_scoring"]["emblems"]) == 18
    empty = await invoke({"account_id": 101, "version_pattern": "8[.]00"})
    assert empty["matches"] == [] and empty["coverage"]["history_exhausted"] is True


@pytest.mark.asyncio
async def test_explicit_version_pattern_does_not_require_dated_patch_labels() -> None:
    class UndatedPatchClient(FantasyContractClient):
        async def get_patches(self) -> list[dict[str, Any]]:
            return [
                {"id": 60, "name": "7.40"},
                {"id": 61, "name": "7.41"},
            ]

    payload = await invoke(
        {
            "account_id": 101,
            "match_count": 1,
            "version_pattern": ".*",
            "tournament_tiers": ["all"],
        },
        UndatedPatchClient(),
    )

    assert "error" not in payload
    assert payload["filters"]["patch"] == ".*"
    assert [item["context"]["match_id"] for item in payload["matches"]] == [2]


@pytest.mark.asyncio
async def test_latest_patch_selection_accepts_iso_release_dates() -> None:
    class IsoPatchClient(FantasyContractClient):
        async def get_patches(self) -> list[dict[str, Any]]:
            return [
                {"id": 60, "name": "7.40", "date": "2025-07-01T00:00:00.000Z"},
                {"id": 61, "name": "7.41", "date": "2026-07-01T00:00:00.000Z"},
            ]

    payload = await invoke({"account_id": 101, "match_count": 1}, IsoPatchClient())

    assert "error" not in payload
    assert payload["filters"]["patch"] == "7.41"
    assert [item["context"]["match_id"] for item in payload["matches"]] == [2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"version_pattern": "7[.]40"},
        {"start_date": "2030-01-01"},
        {"end_date": "2020-01-01"},
        {"tournament_tiers": ["professional"]},
    ],
)
async def test_focused_filters_combine_before_post_filter_limit(arguments: dict[str, Any]) -> None:
    payload = await invoke({"account_id": 101, "match_count": 1, **arguments})
    assert payload["matches"] == []
    assert payload["returned_count"] == 0


@pytest.mark.asyncio
async def test_validation_and_ambiguity_happen_before_detail_reads() -> None:
    fake = FantasyContractClient()
    invalid = await invoke({"account_id": 101, "include": ["raw"]}, fake)
    assert invalid["error"]["valid_values"] == ["fantasy_scoring"]
    ambiguous = await invoke({"player_name": "Duplicate"}, fake)
    assert [item["account_id"] for item in ambiguous["candidates"]] == [102, 103]
    assert fake.match_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 20, 100])
async def test_public_count_boundaries_are_accepted(count: int) -> None:
    payload = await invoke({"account_id": 101, "match_count": count})
    assert "error" not in payload
    assert payload["returned_count"] == min(count, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 101])
async def test_public_count_out_of_bounds_fails_before_details(count: int) -> None:
    fake = FantasyContractClient()
    payload = await invoke({"account_id": 101, "match_count": count}, fake)
    assert payload["error"]["code"] == "invalid_request"
    assert fake.match_calls == 0


class PartialClient(FantasyContractClient):
    async def get_match(self, match_id: int) -> dict[str, Any]:
        if match_id == 2:
            raise UpstreamError("upstream_timeout", "OpenDota timed out", retry_exhausted=True)
        return await super().get_match(match_id)


class ExhaustedClient(FantasyContractClient):
    async def get_pro_players(self) -> list[dict[str, Any]]:
        raise UpstreamError(
            "upstream_rate_limited",
            "OpenDota rate-limit recovery exhausted the attempt budget",
            retry_exhausted=True,
            retryable_later=True,
            reason="attempt_limit",
            retry_after_seconds=2,
        )


@pytest.mark.asyncio
async def test_partial_match_failure_preserves_evidence_and_warns() -> None:
    payload = await invoke({"account_id": 101}, PartialClient())
    assert [item["context"]["match_id"] for item in payload["matches"]] == [1]
    assert any(item["code"] == "partial_match_failures" for item in payload["warnings"])


@pytest.mark.asyncio
async def test_retry_exhaustion_is_sanitized_and_actionable() -> None:
    payload = await invoke({"account_id": 101}, ExhaustedClient())
    assert payload["error"]["code"] == "upstream_rate_limited"
    assert payload["error"]["retry_exhausted"] is True
    assert payload["error"]["retry_after_seconds"] == 2
    assert "traceback" not in str(payload).lower()


@pytest.mark.asyncio
async def test_cancellation_propagates_from_fantasy_tool() -> None:
    class CancelledClient(FantasyContractClient):
        async def get_pro_players(self) -> list[dict[str, Any]]:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await FantasyService(CancelledClient()).get_fantasy(account_id=101)  # type: ignore[arg-type]


class BoundsClient(FantasyContractClient):
    def __init__(self, *, cheap_rejection: bool) -> None:
        super().__init__()
        self.cheap_rejection = cheap_rejection

    async def get_player_matches(
        self, _account_id: int, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        if offset >= 500:
            return []
        return [
            {
                "match_id": 10_000 + value,
                "start_time": 1 if self.cheap_rejection else 1783000000 - value,
                "leagueid": 10,
            }
            for value in range(offset, min(offset + limit, 500))
        ]

    async def get_match(self, match_id: int) -> dict[str, Any]:
        result = await super().get_match(1)
        result["match_id"] = match_id
        result["leagueid"] = 0
        return result


@pytest.mark.asyncio
async def test_exact_history_and_hydrated_detail_safety_boundaries() -> None:
    history = await invoke(
        {"account_id": 101, "start_date": "2026-01-01"},
        BoundsClient(cheap_rejection=True),
    )
    assert history["coverage"] == {
        "history_records_examined": 500,
        "details_requested": 0,
        "details_usable": 0,
        "history_exhausted": False,
        "truncated": True,
        "terminal_reason": "history_record_limit",
    }
    details = await invoke(
        {"account_id": 101, "tournament_tiers": ["all"]},
        BoundsClient(cheap_rejection=False),
    )
    assert details["coverage"]["details_requested"] == 200
    assert details["coverage"]["terminal_reason"] == "hydrated_detail_limit"
    assert details["coverage"]["truncated"] is True


@pytest.mark.asyncio
async def test_tool_schema_annotations_description_and_resource_contract(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    async with Client(create_server(client=FantasyContractClient())) as session:  # type: ignore[arg-type]
        tools = await session.list_tools()
        resources = await session.list_resources()
        content = await session.read_resource("opendota://fantasy/ti-2026/scoring")
    tool = next(item for item in tools if item.name == "get_pro_player_fantasy")
    assert tool.annotations.readOnlyHint is True and tool.annotations.idempotentHint is True
    for phrase in ("slim", "500", "200", "never pubs", "fantasy_scoring"):
        assert phrase in tool.description
    assert set(tool.inputSchema["properties"]) == {
        "account_id",
        "player_name",
        "match_count",
        "version_pattern",
        "start_date",
        "end_date",
        "tournament_tiers",
        "include",
    }
    assert all(
        "pub" not in name and "provenance" not in name for name in tool.inputSchema["properties"]
    )
    assert len(resources) == 1
    assert resources[0].mimeType == "application/json"
    text = content[0].text if isinstance(content, list) else content.text
    assert json.loads(text)["edition"] == "ti-2026-v1"


@pytest.mark.asyncio
async def test_resource_is_deterministic_package_relative_and_zero_network(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    no_network_client = object()
    async with Client(create_server(client=no_network_client)) as session:  # type: ignore[arg-type]
        listed = await session.list_resources()
        first = await session.read_resource("opendota://fantasy/ti-2026/scoring")
        second = await session.read_resource("opendota://fantasy/ti-2026/scoring")
    resource = listed[0]
    assert str(resource.uri) == "opendota://fantasy/ti-2026/scoring"
    assert resource.name == "ti_2026_fantasy_scoring"
    assert resource.mimeType == "application/json"
    assert resource.annotations.audience == ["assistant"]
    assert resource.annotations.priority == 1.0
    first_text = first[0].text if isinstance(first, list) else first.text
    second_text = second[0].text if isinstance(second, list) else second.text
    assert first_text == second_text


def retry_settings(tmp_path) -> Settings:
    return Settings(
        max_attempts=2,
        retry_base_delays=(0.1,),
        retry_jitter_ratio=0,
        retry_delay_cap=2,
        retry_delay_budget=2,
        retry_elapsed_budget=5,
        cache_dir=tmp_path / "cache",
    )


@pytest.mark.asyncio
async def test_fantasy_tool_recovers_through_real_retry_after_boundary(tmp_path) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        path = request.url.path
        if path.endswith("/proPlayers"):
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "0.2"})
            return httpx.Response(200, json=[{"account_id": 101, "name": "Example"}])
        if path.endswith("/constants/patch"):
            return httpx.Response(200, json=[{"id": 61, "name": "7.41", "date": 1782864000}])
        if path.endswith("/leagues"):
            return httpx.Response(200, json=[{"leagueid": 10, "name": "TI", "tier": "premium"}])
        if path.endswith("/heroes") or path.endswith("/players/101/matches"):
            return httpx.Response(200, json=[])
        raise AssertionError(path)

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async with OpenDotaClient(
        retry_settings(tmp_path), transport=httpx.MockTransport(handler), sleeper=sleeper
    ) as runtime:
        payload = await invoke({"account_id": 101}, runtime)  # type: ignore[arg-type]
    assert payload["matches"] == []
    assert attempts == 2 and delays == [0.2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_code", "expected_calls"),
    [(401, "upstream_rejected", 1), (429, "upstream_rate_limited", 2)],
)
async def test_fantasy_tool_real_nonretryable_and_exhausted_failures(
    tmp_path, status: int, expected_code: str, expected_calls: int
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Retry-After": "0.2"})

    async def no_sleep(_delay: float) -> None:
        return None

    async with OpenDotaClient(
        retry_settings(tmp_path), transport=httpx.MockTransport(handler), sleeper=no_sleep
    ) as runtime:
        payload = await invoke({"account_id": 101}, runtime)  # type: ignore[arg-type]
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["retry_exhausted"] is (status == 429)
    assert calls == expected_calls
