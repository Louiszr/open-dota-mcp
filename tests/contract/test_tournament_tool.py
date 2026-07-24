from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

import httpx
import pytest
from fastmcp import Client

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.pagination import SnapshotRegistry
from open_dota_mcp.server import create_server
from open_dota_mcp.services.matches import MatchDiscoveryService


def tournament_match(match_id: int, started: int) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "start_time": started,
        "leagueid": 10,
        "radiant_team_id": 1,
        "radiant_name": "Radiant",
        "dire_team_id": 2,
        "dire_name": "Dire",
        "radiant_win": match_id % 2 == 0,
        "radiant_score": 30,
        "dire_score": 20,
    }


class TournamentClient:
    def __init__(self) -> None:
        self.leagues = [
            {"leagueid": 10, "name": "DreamLeague Season 30", "tier": "premium"},
            {"leagueid": 11, "name": "DreamLeague Season 29", "tier": "professional"},
            {"leagueid": 12, "name": "Amateur Cup", "tier": "amateur"},
            {"leagueid": 13, "name": "Empty Pro", "tier": "professional"},
        ]
        self.matches = [tournament_match(value, value * 100) for value in range(1, 206)]

    async def get_leagues(self) -> list[dict[str, Any]]:
        return deepcopy(self.leagues)

    async def get_league_matches(self, league_id: int) -> list[dict[str, Any]]:
        return deepcopy(self.matches if league_id == 10 else [])


@pytest.mark.asyncio
async def test_id_exact_name_ambiguity_ineligible_and_empty() -> None:
    service = MatchDiscoveryService(TournamentClient(), SnapshotRegistry())  # type: ignore[arg-type]
    by_id = await service.list_tournament_matches(league_id=10, page_size=20)
    assert by_id.league.league_id == 10
    assert len(by_id.matches) == 20
    assert by_id.matches[0].match_id == 205
    exact = await service.list_tournament_matches(tournament_name="dreamleague-season 30")
    assert exact.league.league_id == 10
    ambiguous = await service.list_tournament_matches(tournament_name="dreamleague")
    assert len(ambiguous.candidates) == 2
    assert ambiguous.warnings[0].status == "needs_selection"
    amateur = await service.list_tournament_matches(league_id=12)
    assert amateur.error.code == "ineligible_league"
    empty = await service.list_tournament_matches(league_id=13)
    assert empty.matches == [] and empty.page.terminal is True


@pytest.mark.asyncio
async def test_unbounded_terminal_snapshot_is_immutable_and_no_repeat() -> None:
    fake = TournamentClient()
    service = MatchDiscoveryService(fake, SnapshotRegistry())  # type: ignore[arg-type]
    response = await service.list_tournament_matches(league_id=10, page_size=100)
    ids = [record.match_id for record in response.matches]
    token = response.page.continuation_token
    fake.matches.append(tournament_match(999, 999999))
    while token:
        response = await service.list_tournament_matches(continuation_token=token)
        ids.extend(record.match_id for record in response.matches)
        token = response.page.continuation_token
    assert len(ids) == 205 and len(set(ids)) == 205 and 999 not in ids
    fresh = await service.list_tournament_matches(league_id=10, page_size=1)
    assert fresh.matches[0].match_id == 999


@pytest.mark.asyncio
async def test_token_replay_mismatch_cross_tool_and_page_boundaries() -> None:
    service = MatchDiscoveryService(TournamentClient(), SnapshotRegistry())  # type: ignore[arg-type]
    for page_size in (0, 101):
        invalid = await service.list_tournament_matches(league_id=10, page_size=page_size)
        assert invalid.error.code == "invalid_page_size"
    first = await service.list_tournament_matches(league_id=10, page_size=1)
    token = first.page.continuation_token
    mismatch = await service.list_tournament_matches(
        league_id=11, page_size=1, continuation_token=token
    )
    assert mismatch.error.code == "invalid_continuation"
    second = await service.list_tournament_matches(continuation_token=token)
    assert second.matches
    replay = await service.list_tournament_matches(continuation_token=token)
    assert replay.error.code == "invalid_continuation"


@pytest.mark.asyncio
async def test_duplicate_conflict_and_partial_labels_emit_sparse_warnings() -> None:
    fake = TournamentClient()
    duplicate = tournament_match(1, 100)
    duplicate["radiant_score"] = 99
    fake.matches = [tournament_match(1, 100), duplicate]
    service = MatchDiscoveryService(fake, SnapshotRegistry())  # type: ignore[arg-type]
    response = await service.list_tournament_matches(league_id=10)
    assert len(response.matches) == 1
    assert response.matches[0].warnings[0].code == "inconsistent_duplicate_match"


@pytest.mark.asyncio
async def test_mcp_retry_after_recovery_exhaustion_and_nonretryable_failure() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path.endswith("/leagues"):
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(
                200, json=[{"leagueid": 10, "name": "DreamLeague", "tier": "premium"}]
            )
        return httpx.Response(200, json=[tournament_match(1, 100)])

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    upstream = OpenDotaClient(
        transport=httpx.MockTransport(handler), sleeper=sleeper, jitter=lambda _upper: 0
    )
    async with Client(create_server(client=upstream)) as session:
        response = await session.call_tool("list_pro_tournament_matches", {"league_id": 10})
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
            failure = await session.call_tool("list_pro_tournament_matches", {"league_id": 10})
        await upstream.aclose()
        assert failure.structured_content["error"]["code"] == expected
        assert failure.structured_content["error"]["retry_exhausted"] is (status == 503)


@pytest.mark.asyncio
async def test_tournament_cancellation_and_caller_deadline_propagate() -> None:
    class SlowClient(TournamentClient):
        async def get_leagues(self) -> list[dict[str, Any]]:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    service = MatchDiscoveryService(SlowClient(), SnapshotRegistry())  # type: ignore[arg-type]
    task = asyncio.create_task(service.list_tournament_matches(league_id=10))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await service.list_tournament_matches(league_id=10)
