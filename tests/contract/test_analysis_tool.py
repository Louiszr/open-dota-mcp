from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.pagination import SnapshotRegistry
from open_dota_mcp.server import create_server

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "opendota" / "analysis.json").read_text()
)


class ContractClient:
    def __init__(self) -> None:
        self.data = deepcopy(FIXTURE)
        self.calls = 0
        self.match_calls = 0

    async def get_team(self, team_id: int) -> dict[str, Any]:
        self.calls += 1
        return self.data["team"] if team_id == 1 else {}

    async def get_patches(self) -> list[dict[str, Any]]:
        self.calls += 1
        return self.data["patches"]

    async def get_team_matches(self, _team_id: int) -> list[dict[str, Any]]:
        self.calls += 1
        return self.data["team_matches"]

    async def get_leagues(self) -> list[dict[str, Any]]:
        self.calls += 1
        return self.data["leagues"]

    async def get_heroes(self) -> list[dict[str, Any]]:
        self.calls += 1
        return self.data["heroes"]

    async def get_pro_players(self) -> list[dict[str, Any]]:
        self.calls += 1
        return self.data["pro_players"]

    async def get_match(self, match_id: int) -> dict[str, Any]:
        self.calls += 1
        self.match_calls += 1
        return self.data["details"][str(match_id)]


async def invoke(fake: ContractClient, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(
        create_server(client=fake, registry=SnapshotRegistry())  # type: ignore[arg-type]
    ) as session:
        result = await session.call_tool("analyze_pro_team_drafts", arguments)
    return result.structured_content


@pytest.mark.asyncio
async def test_public_schema_annotations_and_description_document_bounded_contract() -> None:
    fake = ContractClient()
    async with Client(create_server(client=fake)) as session:  # type: ignore[arg-type]
        tools = await session.list_tools()
    assert len(tools) == 4
    tool = next(value for value in tools if value.name == "analyze_pro_team_drafts")
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert set(tool.inputSchema["properties"]) == {
        "team_id",
        "lookback_count",
        "version_pattern",
        "tournament_tiers",
        "side",
        "result",
        "first_ban",
        "include",
        "page_size",
        "continuation_cursor",
    }
    for phrase in ("slim", "premium", "full-string", "five", "25", "next_cursor"):
        assert phrase in tool.description


@pytest.mark.asyncio
async def test_slim_default_and_empty_success_exclude_prohibited_fields() -> None:
    fake = ContractClient()
    payload = await invoke(fake, {"team_id": 1})
    assert payload["team"] == {"team_id": 1, "name": "Radiant Pro"}
    assert payload["coverage"] == {"examined": 4, "parsed": 2, "unparsed": 2}
    assert len(payload["matches"]) == 1
    match = payload["matches"][0]
    assert match["opponent"]["team_id"] == 2
    assert {"draft", "lanes", "economy", "structures", "objectives"}.isdisjoint(match)
    prohibited = ("source", "provenance", "quality", "warnings", "league_id", "patch_id")
    assert all(value not in str(payload) for value in prohibited)
    empty = await invoke(ContractClient(), {"team_id": 1, "version_pattern": "8[.]00"})
    assert empty["matches"] == [] and empty["coverage"]["examined"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({}, "invalid_team_id"),
        ({"team_id": -1}, "invalid_team_id"),
        ({"team_id": 1, "lookback_count": 0}, "invalid_lookback_count"),
        ({"team_id": 1, "version_pattern": "("}, "invalid_version_expression"),
        ({"team_id": 1, "tournament_tiers": ["elite"]}, "invalid_tournament_tiers"),
        ({"team_id": 1, "side": "middle"}, "invalid_filter"),
        ({"team_id": 1, "include": ["draft", "draft"]}, "invalid_include"),
        ({"team_id": 1, "page_size": 0}, "invalid_page_size"),
        ({"continuation_cursor": "bad"}, "invalid_continuation"),
    ],
)
async def test_all_validation_errors_are_concise_and_actionable(
    arguments: dict[str, Any], code: str
) -> None:
    payload = await invoke(ContractClient(), arguments)
    assert payload["error"]["code"] == code
    assert set(payload) == {"error"}
    assert "traceback" not in str(payload).lower() and "regex." not in str(payload)
    if code == "invalid_tournament_tiers":
        assert payload["error"]["valid_values"] == [
            "premium",
            "professional",
            "amateur",
            "all",
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("group", ["draft", "lanes", "economy", "structures", "objectives"])
async def test_every_supported_group_is_independently_additive(group: str) -> None:
    payload = await invoke(ContractClient(), {"team_id": 1, "include": [group]})
    match = payload["matches"][0]
    assert group in match
    assert ({"draft", "lanes", "economy", "structures", "objectives"} - {group}).isdisjoint(match)


@pytest.mark.asyncio
async def test_all_groups_and_contract_example_shape() -> None:
    groups = ["draft", "lanes", "economy", "structures", "objectives"]
    payload = await invoke(ContractClient(), {"team_id": 1, "include": groups})
    match = payload["matches"][0]
    assert all(group in match for group in groups)
    assert match["draft"]["actions"][-1]["hero"] == "Lina"
    assert match["economy"]["hero_total_gold"][0]["at_10"] == 4700


@pytest.mark.asyncio
async def test_page_sizes_terminal_cursor_replay_mismatch_and_no_continuation_io() -> None:
    fake = ContractClient()
    base = deepcopy(fake.data["details"]["2001"])
    fake.data["team_matches"] = []
    fake.data["details"] = {}
    for value in range(30):
        match_id = 3000 + value
        detail = deepcopy(base)
        detail["match_id"] = match_id
        detail["start_time"] = 1784779200 - value
        fake.data["details"][str(match_id)] = detail
        fake.data["team_matches"].append(
            {"match_id": match_id, "start_time": detail["start_time"], "duration": 1300}
        )
    registry = SnapshotRegistry(token_factory=iter(["one", "two", "three"]).__next__)
    async with Client(create_server(client=fake, registry=registry)) as session:  # type: ignore[arg-type]
        first = await session.call_tool(
            "analyze_pro_team_drafts",
            {"team_id": 1, "lookback_count": 30, "page_size": 25},
        )
        first_payload = first.structured_content
        assert len(first_payload["matches"]) == 25 and first_payload["next_cursor"] == "one"
        calls = fake.calls
        final = await session.call_tool("analyze_pro_team_drafts", {"continuation_cursor": "one"})
        assert len(final.structured_content["matches"]) == 5
        assert "next_cursor" not in final.structured_content and fake.calls == calls
        replay = await session.call_tool("analyze_pro_team_drafts", {"continuation_cursor": "one"})
        assert replay.structured_content["error"]["code"] == "invalid_continuation"


@pytest.mark.asyncio
async def test_no_detail_read_occurs_after_expression_rejection() -> None:
    fake = ContractClient()
    payload = await invoke(fake, {"team_id": 1, "version_pattern": "("})
    assert payload["error"]["code"] == "invalid_version_expression"
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_unknown_team_and_unavailable_patch_catalog_are_actionable() -> None:
    missing_team = await invoke(ContractClient(), {"team_id": 999})
    assert missing_team["error"]["code"] == "identity_not_found"
    assert "lookup" in missing_team["error"]["message"]

    fake = ContractClient()
    fake.data["patches"] = [{"id": 61, "name": "7.41", "date": "not-a-date"}]
    unavailable = await invoke(fake, {"team_id": 1})
    assert unavailable["error"]["code"] == "patch_catalog_unavailable"
    assert fake.match_calls == 0


@pytest.mark.asyncio
async def test_analysis_tool_retry_recovery_exhaustion_and_nonretryable_failure() -> None:
    attempts = 0
    delays: list[float] = []

    def recovery_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        path = request.url.path
        if path.endswith("/teams/1"):
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"team_id": 1, "name": "Radiant Pro"})
        if path.endswith("/constants/patch"):
            return httpx.Response(200, json=[{"id": 61, "name": "7.41", "date": 1782864000}])
        return httpx.Response(200, json=[])

    async def sleep(delay: float) -> None:
        delays.append(delay)

    upstream = OpenDotaClient(
        transport=httpx.MockTransport(recovery_handler),
        sleeper=sleep,
        jitter=lambda _upper: 0,
    )
    async with Client(create_server(client=upstream)) as session:
        recovered = await session.call_tool("analyze_pro_team_drafts", {"team_id": 1})
    await upstream.aclose()
    assert recovered.structured_content["coverage"]["examined"] == 0
    assert attempts == 2 and delays == [2]

    for status, code in [(503, "upstream_unavailable"), (403, "upstream_rejected")]:
        upstream = OpenDotaClient(
            Settings(max_attempts=1),
            transport=httpx.MockTransport(
                lambda _request, status_code=status: httpx.Response(status_code)
            ),
        )
        async with Client(create_server(client=upstream)) as session:
            failed = await session.call_tool("analyze_pro_team_drafts", {"team_id": 1})
        await upstream.aclose()
        error = failed.structured_content["error"]
        assert error["code"] == code
        if status == 503:
            assert error["reason"] == "attempt_limit"
        else:
            assert "reason" not in error


@pytest.mark.asyncio
async def test_analysis_tool_cancellation_propagates_without_masking() -> None:
    class BlockingClient(ContractClient):
        async def get_team(self, _team_id: int) -> dict[str, Any]:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async with Client(create_server(client=BlockingClient())) as session:  # type: ignore[arg-type]
        task = asyncio.create_task(session.call_tool("analyze_pro_team_drafts", {"team_id": 1}))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_timeout_expression_is_sanitized_and_stops_before_detail_reads() -> None:
    fake = ContractClient()
    fake.data["patches"][-1]["name"] = "a" * 100_000 + "!"
    payload = await invoke(fake, {"team_id": 1, "version_pattern": "(a+)+$"})
    assert payload["error"]["code"] == "invalid_version_expression"
    assert "timed out" in payload["error"]["message"]
    assert fake.match_calls == 0


@pytest.mark.asyncio
async def test_cursor_mismatch_and_expiry_require_restart_without_upstream_io() -> None:
    fake = ContractClient()
    base = deepcopy(fake.data["details"]["2001"])
    second = deepcopy(base)
    second["match_id"] = 5002
    second["start_time"] -= 1
    fake.data["details"] = {"2001": base, "5002": second}
    fake.data["team_matches"] = [
        {"match_id": 2001, "start_time": base["start_time"], "duration": 1300},
        {"match_id": 5002, "start_time": second["start_time"], "duration": 1300},
    ]
    now = {"value": 0.0}
    registry = SnapshotRegistry(
        ttl_seconds=1,
        clock=lambda: now["value"],
        token_factory=iter(["cursor"]).__next__,
    )
    async with Client(create_server(client=fake, registry=registry)) as session:  # type: ignore[arg-type]
        first = (
            await session.call_tool("analyze_pro_team_drafts", {"team_id": 1, "page_size": 1})
        ).structured_content
        calls = fake.calls
        mismatch = (
            await session.call_tool(
                "analyze_pro_team_drafts",
                {"team_id": 1, "continuation_cursor": first["next_cursor"]},
            )
        ).structured_content
        assert mismatch["error"]["code"] == "invalid_continuation"
        now["value"] = 2
        expired = (
            await session.call_tool(
                "analyze_pro_team_drafts", {"continuation_cursor": first["next_cursor"]}
            )
        ).structured_content
    assert expired["error"]["code"] == "continuation_expired"
    assert expired["error"]["restart_required"] is True
    assert fake.calls == calls
