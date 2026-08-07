from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastmcp import Client

from open_dota_mcp.errors import UpstreamError
from open_dota_mcp.server import create_server


class PlayerJourneyClient:
    def __init__(self, *, fail_identity: bool = False) -> None:
        self.fail_identity = fail_identity
        self.match_calls = 0

    async def get_pro_players(self) -> list[dict[str, Any]]:
        if self.fail_identity:
            raise UpstreamError(
                "upstream_unavailable",
                "OpenDota availability recovery exhausted the attempt budget",
                retry_exhausted=True,
                retryable_later=True,
            )
        return [
            {"account_id": 101, "name": "Twin"},
            {"account_id": 102, "name": "Twin"},
        ]

    async def get_patches(self) -> list[dict[str, Any]]:
        return [{"id": 61, "name": "7.41", "date": 1782864000}]

    async def get_leagues(self) -> list[dict[str, Any]]:
        return [{"leagueid": 10, "name": "TI 2026", "tier": "premium"}]

    async def get_heroes(self) -> list[dict[str, Any]]:
        return [{"id": 25, "localized_name": "Lina"}]

    async def get_player_matches(
        self, account_id: int, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        if offset:
            return []
        base = 1000 if account_id == 101 else 2000
        return [
            {"match_id": base + digit, "start_time": 1783000000 + digit, "leagueid": 10}
            for digit in range(5, 0, -1)
        ][:limit]

    async def get_match(self, match_id: int) -> dict[str, Any]:
        self.match_calls += 1
        digit = match_id % 10
        account_id = 101 if match_id < 2000 else 102
        first_series = 501 if account_id == 101 else 601
        series_id = first_series if digit >= 4 else first_series + 1 if digit >= 2 else None
        deaths = digit if account_id == 101 else 6 - digit
        scale = 1 if account_id == 101 else 2
        return {
            "match_id": match_id,
            "version": 21,
            "start_time": 1783000000 + digit,
            "duration": 1800,
            "patch": 61,
            "leagueid": 10,
            "league": {"name": "TI 2026", "tier": "premium"},
            "series_id": series_id,
            "radiant_team_id": 1,
            "dire_team_id": 2,
            "radiant_name": "Radiant Pro",
            "dire_name": "Dire Pro",
            "radiant_win": True,
            "radiant_score": 20,
            "dire_score": 10,
            "players": [
                {
                    "account_id": account_id,
                    "player_slot": 0,
                    "hero_id": 25,
                    "kills": digit * scale,
                    "deaths": deaths,
                    "assists": 5,
                    "last_hits": 100,
                    "denies": 5,
                    "gold_per_min": 500,
                    "tower_kills": 0,
                    "obs_placed": 0,
                    "camps_stacked": 0,
                    "rune_pickups": 0,
                    "item_uses": {"smoke_of_deceit": 0},
                    "roshans_killed": 0,
                    "stuns": digit * 0.5 * scale,
                    "couriers_killed": 0,
                    "firstblood_claimed": digit % 2 == 1,
                },
                {
                    "account_id": 999,
                    "player_slot": 128,
                    "firstblood_claimed": digit % 2 == 0,
                },
            ],
            "objectives": [],
        }


@dataclass(frozen=True)
class ProjectionCase:
    player: int
    emblem: str
    tier: str
    modifier: str | None
    expected: float | None


CASES = [
    ProjectionCase(101, "kills", "I", None, 1059.3),
    ProjectionCase(101, "kills", "V", "Unique", 3129.75),
    ProjectionCase(101, "deaths", "I", None, 3217.5),
    ProjectionCase(101, "stuns", "II", None, 58.5),
    ProjectionCase(101, "first_blood", "I", None, 2127.4),
    ProjectionCase(101, "madstone", "I", None, None),
    ProjectionCase(101, "kills", "II", "the Underdog", 1327.014),
    ProjectionCase(101, "kills", "IV", "Fractal", None),
    ProjectionCase(101, "deaths", "V", "Unique", 9506.25),
    ProjectionCase(101, "stuns", "IV", "the Underdog", 95.4),
    ProjectionCase(102, "kills", "I", None, 2118.6),
    ProjectionCase(102, "kills", "V", "Unique", 6259.5),
    ProjectionCase(102, "deaths", "I", None, 3646.5),
    ProjectionCase(102, "stuns", "II", None, 117.0),
    ProjectionCase(102, "first_blood", "I", None, 2127.4),
    ProjectionCase(102, "madstone", "I", None, None),
    ProjectionCase(102, "kills", "II", "the Underdog", 2654.028),
    ProjectionCase(102, "kills", "IV", "Fractal", None),
    ProjectionCase(102, "deaths", "V", "Unique", 10773.75),
    ProjectionCase(102, "stuns", "IV", "the Underdog", 190.8),
]


def project_best_confirmed_series(
    case: ProjectionCase, matches: list[dict[str, Any]], reference: dict[str, Any]
) -> float | None:
    """Apply one candidate configuration to observed pre-modifier map scores."""
    tier = next(item for item in reference["quality_tiers"] if item["tier"] == case.tier)
    modifier_factor = 1.0
    if case.modifier:
        modifiers = [*reference["traits"], *reference["titles"]]
        modifier = next(item for item in modifiers if item["name"] == case.modifier)
        if modifier["status"] == "unknown" or modifier["numeric_effect"] is None:
            return None
        modifier_factor += modifier["numeric_effect"]
    grouped: dict[int, list[float]] = {}
    for match in matches:
        series_id = match["context"]["series_id"]
        score = next(
            item["raw_points"]
            for item in match["fantasy_scoring"]["emblems"]
            if item["key"] == case.emblem
        )
        if series_id is not None and score is not None:
            grouped.setdefault(series_id, []).append(float(score))
    if not grouped:
        return None
    raw_best = max(sum(sorted(values, reverse=True)[:2]) for values in grouped.values())
    return raw_best * tier["multiplier"] * modifier_factor


@pytest.mark.asyncio
async def test_id_and_two_call_name_journey_empty_scoring_and_sanitized_failure() -> None:
    fake = PlayerJourneyClient()
    async with Client(create_server(client=fake)) as session:  # type: ignore[arg-type]
        ambiguous = await session.call_tool("get_pro_player_fantasy", {"player_name": "Twin"})
        assert [item["account_id"] for item in ambiguous.structured_content["candidates"]] == [
            101,
            102,
        ]
        assert fake.match_calls == 0
        resolved = await session.call_tool(
            "get_pro_player_fantasy",
            {"account_id": 101, "include": ["fantasy_scoring"], "tournament_tiers": ["all"]},
        )
        empty = await session.call_tool(
            "get_pro_player_fantasy", {"account_id": 101, "version_pattern": "8[.]00"}
        )
    payload = resolved.structured_content
    assert [item["context"]["match_id"] for item in payload["matches"]] == [
        1005,
        1004,
        1003,
        1002,
        1001,
    ]
    assert len(payload["matches"][0]["fantasy_scoring"]["emblems"]) == 18
    assert empty.structured_content["matches"] == []
    assert "quality" not in str(payload) and "loadout" not in str(payload)
    async with Client(create_server(client=PlayerJourneyClient(fail_identity=True))) as session:  # type: ignore[arg-type]
        failed = await session.call_tool("get_pro_player_fantasy", {"account_id": 101})
    assert failed.structured_content["error"]["retry_exhausted"] is True
    assert "traceback" not in str(failed.structured_content).lower()


@pytest.mark.asyncio
async def test_fixed_twenty_case_tool_and_resource_evaluation_corpus() -> None:
    fake = PlayerJourneyClient()
    async with Client(create_server(client=fake)) as session:  # type: ignore[arg-type]
        evidence = {
            player: (
                await session.call_tool(
                    "get_pro_player_fantasy",
                    {"account_id": player, "include": ["fantasy_scoring"]},
                )
            ).structured_content["matches"]
            for player in (101, 102)
        }
        resource = await session.read_resource("opendota://fantasy/ti-2026/scoring")
    text = resource[0].text if isinstance(resource, list) else resource.text
    reference = json.loads(text)
    passed = 0
    for case in CASES:
        actual = project_best_confirmed_series(case, evidence[case.player], reference)
        if case.expected is None:
            passed += actual is None
        else:
            passed += actual == pytest.approx(case.expected)
    assert len(CASES) == 20 and passed == 20
    assert any(item["context"]["series_id"] is None for item in evidence[101])
    assert all("loadout" not in str(item) and "quality" not in str(item) for item in evidence[101])


class FixtureScaleClient(PlayerJourneyClient):
    def __init__(self, records: list[dict[str, Any]]) -> None:
        super().__init__()
        self.records = {item["match_id"]: item for item in records}

    async def get_patches(self) -> list[dict[str, Any]]:
        return [
            {"id": 60, "name": "7.40", "date": 1751328000},
            {"id": 61, "name": "7.41", "date": 1782864000},
        ]

    async def get_leagues(self) -> list[dict[str, Any]]:
        return [
            {"leagueid": 10, "name": "Premium Cup", "tier": "premium"},
            {"leagueid": 11, "name": "Pro Cup", "tier": "professional"},
            {"leagueid": 12, "name": "Amateur Cup", "tier": "amateur"},
        ]

    async def get_player_matches(
        self, account_id: int, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        del account_id
        ordered = sorted(self.records.values(), key=lambda item: item["match_id"], reverse=True)
        return [
            {
                "match_id": item["match_id"],
                "start_time": fixture_start(item["match_id"]),
                "leagueid": {"premium": 10, "professional": 11, "amateur": 12}[item["tier"]],
            }
            for item in ordered[offset : offset + limit]
        ]

    async def get_match(self, match_id: int) -> dict[str, Any]:
        item = self.records[match_id]
        league_id = {"premium": 10, "professional": 11, "amateur": 12}[item["tier"]]
        return {
            **await super().get_match(1000 + match_id % 10),
            "match_id": match_id,
            "start_time": fixture_start(match_id),
            "patch": item["patch"],
            "leagueid": league_id,
            "league": {"name": f"{item['tier']} Cup", "tier": item["tier"]},
            "series_id": item["series_id"],
        }


def fixture_start(match_id: int) -> int:
    """Spread fixture maps over distinct UTC dates for inclusive filtering."""
    return 1782864000 + (match_id - 9000) * 86_400


@pytest.mark.asyncio
async def test_explicit_thirty_map_fixture_filters_order_and_context(fantasy_fixture) -> None:
    records = fantasy_fixture["professional_maps"]
    async with Client(create_server(client=FixtureScaleClient(records))) as session:  # type: ignore[arg-type]
        result = await session.call_tool(
            "get_pro_player_fantasy",
            {
                "account_id": 101,
                "match_count": 100,
                "version_pattern": "7[.](40|41)",
                "tournament_tiers": ["all"],
            },
        )
        focused = await session.call_tool(
            "get_pro_player_fantasy",
            {
                "account_id": 101,
                "match_count": 100,
                "version_pattern": "7[.]40",
                "tournament_tiers": ["professional"],
                "start_date": datetime.fromtimestamp(fixture_start(9014), UTC).date().isoformat(),
                "end_date": datetime.fromtimestamp(fixture_start(9018), UTC).date().isoformat(),
            },
        )
    matches = result.structured_content["matches"]
    assert len(matches) == 30
    assert [item["context"]["match_id"] for item in matches] == sorted(
        (item["match_id"] for item in records), reverse=True
    )
    assert {item["context"]["patch"] for item in matches} == {"7.40", "7.41"}
    assert {item["context"]["tournament_tier"] for item in matches} == {
        "premium",
        "professional",
        "amateur",
    }
    assert matches[0]["context"]["hero"] == {"hero_id": 25, "name": "Lina"}
    required_context = {
        "match_id",
        "start_time",
        "patch",
        "tournament_name",
        "tournament_tier",
        "series_id",
        "player",
        "team",
        "opponent",
        "hero",
        "result",
        "duration_seconds",
        "team_kills",
        "opponent_kills",
    }
    assert all(set(item["context"]) == required_context for item in matches)
    assert [item["context"]["match_id"] for item in focused.structured_content["matches"]] == [
        9018,
        9015,
    ]
