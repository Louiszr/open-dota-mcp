from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastmcp import Client

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.errors import UpstreamError
from open_dota_mcp.server import create_server
from open_dota_mcp.services.roster import RosterService


class RosterContractClient:
    def __init__(self, *, mismatch: bool = False, current_count: int = 5) -> None:
        self.mismatch = mismatch
        self.current_count = current_count
        self.match_calls: list[int] = []

    async def get_team(self, _team_id: int) -> dict[str, Any]:
        return {"team_id": 1, "name": "Radiant Pro"}

    async def get_team_players(self, _team_id: int) -> list[dict[str, Any]]:
        return [
            {"account_id": value, "is_current_team_member": True}
            for value in range(101, 101 + self.current_count)
        ]

    async def get_team_matches(self, _team_id: int) -> list[dict[str, Any]]:
        return [
            {"match_id": 2, "start_time": 1783000002},
            {"match_id": 1, "start_time": 1783000001},
        ]

    async def get_pro_players(self) -> list[dict[str, Any]]:
        return [{"account_id": value, "name": f"P{value}"} for value in range(101, 107)]

    async def get_match(self, match_id: int) -> dict[str, Any]:
        self.match_calls.append(match_id)
        if match_id == 2:
            return {"match_id": 2, "version": None}
        ids = [101, 102, 103, 104, 106 if self.mismatch else 105]
        lanes = [1, 2, 3, 3, 1]
        farm = [80, 55, 70, 20, 10]
        return {
            "match_id": 1,
            "version": 21,
            "start_time": 1783000001,
            "radiant_team_id": 1,
            "dire_team_id": 2,
            "players": [
                {
                    "account_id": account_id,
                    "player_slot": index,
                    "lane_role": lanes[index],
                    "times": [0, 600],
                    "lh_t": [0, farm[index]],
                }
                for index, account_id in enumerate(ids)
            ],
        }


async def invoke(fake: RosterContractClient, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(create_server(client=fake)) as session:  # type: ignore[arg-type]
        result = await session.call_tool("get_pro_team_roster", arguments)
    return result.structured_content


@pytest.mark.asyncio
async def test_newest_usable_exact_membership_and_positions() -> None:
    fake = RosterContractClient()
    payload = await invoke(fake, {"team_id": 1})
    assert fake.match_calls == [2, 1]
    assert payload["source_match"]["match_id"] == 1
    assert len(payload["players"]) == 5
    assert [item["position"] for item in payload["players"]] == [1, 2, 3, 4, 5]
    assert payload["coverage"] == {
        "completed_records_considered": 2,
        "details_requested": 2,
        "parsed_usable": 1,
    }


@pytest.mark.asyncio
async def test_membership_failures_are_bounded_cannot_infer_outcomes() -> None:
    unavailable = await invoke(RosterContractClient(current_count=4), {"team_id": 1})
    assert unavailable["error"]["code"] == "current_roster_unavailable"
    mismatch_fake = RosterContractClient(mismatch=True)
    mismatch = await invoke(mismatch_fake, {"team_id": 1})
    assert mismatch["error"]["code"] == "lineup_mismatch"
    assert "players" not in mismatch and mismatch_fake.match_calls == [2, 1]


class ExhaustedHistoryClient(RosterContractClient):
    async def get_team_matches(self, _team_id: int) -> list[dict[str, Any]]:
        return [
            {"match_id": match_id, "start_time": 1783000000 + match_id}
            for match_id in range(10, 3, -1)
        ]

    async def get_match(self, match_id: int) -> dict[str, Any]:
        self.match_calls.append(match_id)
        return {"match_id": match_id, "version": None}


class RetryExhaustedRosterClient(RosterContractClient):
    async def get_team_players(self, _team_id: int) -> list[dict[str, Any]]:
        raise UpstreamError(
            "upstream_unavailable",
            "OpenDota availability recovery exhausted the attempt budget",
            retry_exhausted=True,
            retryable_later=True,
            reason="attempt_limit",
        )


class PartialRosterClient(RosterContractClient):
    async def get_match(self, match_id: int) -> dict[str, Any]:
        if match_id == 2:
            self.match_calls.append(match_id)
            raise UpstreamError("upstream_timeout", "one record failed", retry_exhausted=True)
        return await super().get_match(match_id)


class NameRosterClient(RosterContractClient):
    async def get_teams_page(self, page: int) -> list[dict[str, Any]]:
        if page:
            return []
        return [
            {"team_id": team_id, "name": f"Radiant {team_id}", "tag": f"R{team_id}"}
            for team_id in range(1, 13)
        ]


class ExactNameRosterClient(RosterContractClient):
    async def get_teams_page(self, page: int) -> list[dict[str, Any]]:
        if page:
            return []
        return [
            {"team_id": 1, "name": "Radiant Pro", "tag": "RP"},
            {"team_id": 2, "name": "Dire Pro", "tag": "DP"},
        ]


@pytest.mark.asyncio
async def test_fixed_five_record_exhaustion_and_partial_detail_recovery() -> None:
    exhausted_fake = ExhaustedHistoryClient()
    exhausted = await invoke(exhausted_fake, {"team_id": 1})
    assert exhausted["error"]["code"] == "lineup_unavailable"
    assert exhausted["coverage"]["details_requested"] == 5
    assert len(exhausted_fake.match_calls) == 5
    partial_fake = PartialRosterClient()
    recovered = await invoke(partial_fake, {"team_id": 1})
    assert len(recovered["players"]) == 5
    assert partial_fake.match_calls == [2, 1]


@pytest.mark.asyncio
async def test_team_name_ambiguity_is_bounded_before_detail_reads() -> None:
    fake = NameRosterClient()
    payload = await invoke(fake, {"team_name": "Radiant"})
    assert len(payload["candidates"]) == 10
    assert fake.match_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", ["Radiant Pro", "RP"])
async def test_unique_exact_team_name_or_tag_auto_resolves(selector: str) -> None:
    payload = await invoke(ExactNameRosterClient(), {"team_name": selector})
    assert payload["team"] == {"team_id": 1, "name": "Radiant Pro"}
    assert len(payload["players"]) == 5


@pytest.mark.asyncio
async def test_roster_retry_exhaustion_and_cancellation_are_structured() -> None:
    exhausted = await invoke(RetryExhaustedRosterClient(), {"team_id": 1})
    assert exhausted["error"]["code"] == "upstream_unavailable"
    assert exhausted["error"]["retry_exhausted"] is True

    class CancelledRosterClient(RosterContractClient):
        async def get_team(self, _team_id: int) -> dict[str, Any]:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await RosterService(CancelledRosterClient()).get_roster(team_id=1)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_roster_schema_description_and_annotations() -> None:
    async with Client(create_server(client=RosterContractClient())) as session:  # type: ignore[arg-type]
        tools = await session.list_tools()
    assert len(tools) == 6
    tool = next(item for item in tools if item.name == "get_pro_team_roster")
    assert tool.annotations.readOnlyHint is True and tool.annotations.idempotentHint is True
    for phrase in ("five", "current members", "latest-observed", "nullable"):
        assert phrase in tool.description


@pytest.mark.asyncio
async def test_roster_tool_uses_real_retry_after_recovery_boundary(tmp_path) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        path = request.url.path
        if path.endswith("/teams/1"):
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "0.2"})
            return httpx.Response(200, json={"team_id": 1, "name": "Radiant Pro"})
        if any(
            path.endswith(suffix)
            for suffix in ("/teams/1/players", "/teams/1/matches", "/proPlayers")
        ):
            return httpx.Response(200, json=[])
        raise AssertionError(path)

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    settings = Settings(
        max_attempts=2,
        retry_base_delays=(0.1,),
        retry_jitter_ratio=0,
        retry_delay_cap=2,
        retry_delay_budget=2,
        retry_elapsed_budget=5,
        cache_dir=tmp_path / "cache",
    )
    async with OpenDotaClient(
        settings, transport=httpx.MockTransport(handler), sleeper=sleeper
    ) as runtime:
        payload = await invoke(runtime, {"team_id": 1})  # type: ignore[arg-type]
    assert payload["error"]["code"] == "current_roster_unavailable"
    assert attempts == 2 and delays == [0.2]


@pytest.mark.asyncio
async def test_roster_tool_real_nonretryable_failure_is_not_retried(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    settings = Settings(
        max_attempts=2,
        retry_base_delays=(0.1,),
        retry_jitter_ratio=0,
        retry_delay_cap=2,
        retry_delay_budget=2,
        retry_elapsed_budget=5,
        cache_dir=tmp_path / "cache",
    )
    async with OpenDotaClient(settings, transport=httpx.MockTransport(handler)) as runtime:
        payload = await invoke(runtime, {"team_id": 1})  # type: ignore[arg-type]
    assert payload["error"]["code"] == "upstream_rejected"
    assert payload["error"]["retry_exhausted"] is False
    assert calls == 1
