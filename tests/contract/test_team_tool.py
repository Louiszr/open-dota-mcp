from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

import httpx
import pytest
from fastmcp import Client

from open_dota_mcp.cache.store import CacheStore
from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.pagination import SnapshotRegistry
from open_dota_mcp.server import create_server
from open_dota_mcp.services.matches import MatchDiscoveryService


def team_match(
    match_id: int,
    started: int,
    *,
    selected_radiant: bool = True,
    radiant_win: bool = True,
) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "start_time": started,
        "leagueid": 10,
        "league_name": "DreamLeague",
        "radiant": selected_radiant,
        "opposing_team_id": 2,
        "opposing_team_name": "Opponent",
        "radiant_win": radiant_win,
        "radiant_score": 30,
        "dire_score": 20,
    }


class TeamClient:
    def __init__(self) -> None:
        self.teams = [
            {"team_id": 1, "name": "Team Spirit", "tag": "TS", "last_match_time": 20},
            {"team_id": 2, "name": "Team Secret", "tag": "TS", "last_match_time": 10},
        ]
        self.matches = [
            team_match(1, 1784779200, selected_radiant=True, radiant_win=True),
            team_match(2, 1784692800, selected_radiant=False, radiant_win=True),
            team_match(3, 1784606400, selected_radiant=True, radiant_win=False),
        ]

    async def get_teams_page(self, page: int) -> list[dict[str, Any]]:
        return deepcopy(self.teams if page == 0 else [])

    async def get_team(self, team_id: int) -> dict[str, Any]:
        return deepcopy(next(team for team in self.teams if team["team_id"] == team_id))

    async def get_team_matches(self, _team_id: int) -> list[dict[str, Any]]:
        return deepcopy(self.matches)


@pytest.mark.asyncio
async def test_id_name_tag_resolution_and_disambiguation() -> None:
    service = MatchDiscoveryService(TeamClient(), SnapshotRegistry())  # type: ignore[arg-type]
    by_id = await service.list_team_matches(team_id=1)
    assert by_id.team.name == "Team Spirit"
    assert by_id.matches[0].selected_team_side == "radiant"
    assert by_id.matches[0].opponent.team_id == 2
    assert by_id.matches[0].opponent.name == "Opponent"
    exact = await service.list_team_matches(team_name="team-spirit")
    assert exact.team.team_id == 1
    ambiguous = await service.list_team_matches(team_name="TS")
    assert [candidate.team_id for candidate in ambiguous.candidates] == [1, 2]
    assert ambiguous.warnings[0].status == "needs_selection"


@pytest.mark.asyncio
async def test_strict_dates_side_result_and_combined_and_filters() -> None:
    service = MatchDiscoveryService(TeamClient(), SnapshotRegistry())  # type: ignore[arg-type]
    filtered = await service.list_team_matches(
        team_id=1,
        start_date="2026-07-22",
        end_date="2026-07-23",
        side="radiant",
        result="win",
    )
    assert [record.match_id for record in filtered.matches] == [1]
    empty = await service.list_team_matches(team_id=1, result="win", side="dire")
    assert empty.matches == [] and empty.page.terminal is True
    for kwargs in [
        {"start_date": "07-23-2026"},
        {"start_date": "2026-07-24", "end_date": "2026-07-23"},
        {"side": "middle"},
        {"result": "draw"},
    ]:
        invalid = await service.list_team_matches(team_id=1, **kwargs)
        assert invalid.error.code in {"invalid_date", "invalid_filter"}


@pytest.mark.asyncio
async def test_team_relative_result_newest_first_and_snapshot_mutation() -> None:
    fake = TeamClient()
    service = MatchDiscoveryService(fake, SnapshotRegistry())  # type: ignore[arg-type]
    first = await service.list_team_matches(team_id=1, page_size=1)
    token = first.page.continuation_token
    fake.matches.append(team_match(99, 1999999999))
    second = await service.list_team_matches(continuation_token=token)
    assert second.matches[0].match_id == 2
    fresh = await service.list_team_matches(team_id=1, page_size=1)
    assert fresh.matches[0].match_id == 99


@pytest.mark.asyncio
async def test_anomalous_side_is_excluded_with_collection_warning() -> None:
    fake = TeamClient()
    anomaly = team_match(8, 1784900000)
    anomaly["opposing_team_id"] = 1
    fake.matches.append(anomaly)
    service = MatchDiscoveryService(fake, SnapshotRegistry())  # type: ignore[arg-type]
    response = await service.list_team_matches(team_id=1)
    assert 8 not in [record.match_id for record in response.matches]
    assert response.warnings[0].code == "anomalous_team_side"


@pytest.mark.asyncio
async def test_full_side_match_projection_remains_compatible() -> None:
    fake = TeamClient()
    fake.matches = [
        {
            "match_id": 7,
            "start_time": 1784779200,
            "leagueid": 10,
            "league_name": "DreamLeague",
            "radiant_team_id": 1,
            "radiant_name": "Team Spirit",
            "dire_team_id": 2,
            "dire_name": "Opponent",
            "radiant_win": True,
            "radiant_score": 30,
            "dire_score": 20,
        }
    ]
    service = MatchDiscoveryService(fake, SnapshotRegistry())  # type: ignore[arg-type]
    response = await service.list_team_matches(team_id=1)
    assert response.matches[0].selected_team_side == "radiant"
    assert response.matches[0].opponent.team_id == 2


@pytest.mark.asyncio
async def test_team_paging_boundaries_replay_and_partial_scores() -> None:
    fake = TeamClient()
    fake.matches = [team_match(value, value * 100) for value in range(1, 105)]
    fake.matches[0]["radiant_score"] = None
    service = MatchDiscoveryService(fake, SnapshotRegistry())  # type: ignore[arg-type]
    first = await service.list_team_matches(team_id=1, page_size=100)
    assert len(first.matches) == 100
    token = first.page.continuation_token
    final = await service.list_team_matches(continuation_token=token)
    assert final.page.terminal is True and len(final.matches) == 4
    replay = await service.list_team_matches(continuation_token=token)
    assert replay.error.code == "invalid_continuation"


@pytest.mark.asyncio
async def test_mcp_retry_after_recovery_exhaustion_and_nonretryable_failure() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path.endswith("/teams/1"):
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"team_id": 1, "name": "Spirit", "tag": "TS"})
        return httpx.Response(200, json=[team_match(1, 100)])

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    upstream = OpenDotaClient(
        transport=httpx.MockTransport(handler), sleeper=sleeper, jitter=lambda _upper: 0
    )
    async with Client(create_server(client=upstream)) as session:
        response = await session.call_tool("list_pro_team_matches", {"team_id": 1})
    await upstream.aclose()
    assert response.structured_content["matches"][0]["match_id"] == 1
    assert attempts == 2 and delays == [0]

    for status, expected in [(503, "upstream_unavailable"), (403, "upstream_rejected")]:
        upstream = OpenDotaClient(
            Settings(max_attempts=2),
            transport=httpx.MockTransport(lambda _request, code=status: httpx.Response(code)),
            sleeper=sleeper,
        )
        async with Client(create_server(client=upstream)) as session:
            failure = await session.call_tool("list_pro_team_matches", {"team_id": 1})
        await upstream.aclose()
        assert failure.structured_content["error"]["code"] == expected
        assert failure.structured_content["error"]["retry_exhausted"] is (status == 503)


@pytest.mark.asyncio
async def test_team_cancellation_and_caller_deadline_propagate() -> None:
    class SlowClient(TeamClient):
        async def get_team(self, team_id: int) -> dict[str, Any]:
            await asyncio.Event().wait()
            raise AssertionError(team_id)

    service = MatchDiscoveryService(SlowClient(), SnapshotRegistry())  # type: ignore[arg-type]
    task = asyncio.create_task(service.list_team_matches(team_id=1))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await service.list_team_matches(team_id=1)


@pytest.mark.asyncio
async def test_cached_and_fresh_team_contracts_are_identical(tmp_path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/teams/1"):
            return httpx.Response(200, json={"team_id": 1, "name": "Spirit", "tag": "TS"})
        return httpx.Response(200, json=[team_match(1, 100)])

    settings = Settings(cache_dir=tmp_path / "cache")
    upstream = OpenDotaClient(
        settings,
        transport=httpx.MockTransport(handler),
        cache_store=CacheStore(settings.cache_dir),
    )
    async with Client(create_server(client=upstream)) as session:
        fresh = await session.call_tool("list_pro_team_matches", {"team_id": 1})
        first_calls = calls
        cached = await session.call_tool("list_pro_team_matches", {"team_id": 1})
    await upstream.aclose()
    assert cached.structured_content == fresh.structured_content
    assert calls == first_calls


@pytest.mark.asyncio
async def test_team_continuation_survives_response_cache_clear(tmp_path) -> None:
    fake = TeamClient()
    fake.matches = [team_match(value, value * 100) for value in range(1, 45)]
    service = MatchDiscoveryService(fake, SnapshotRegistry())  # type: ignore[arg-type]
    first = await service.list_team_matches(team_id=1, page_size=20)
    fake.matches.clear()
    CacheStore(tmp_path / "cache").clear()
    continued = await service.list_team_matches(continuation_token=first.page.continuation_token)
    assert len(continued.matches) == 20
    assert continued.page.page_size == 20 and not continued.page.terminal
