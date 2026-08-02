from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from open_dota_mcp.pagination import SnapshotRegistry
from open_dota_mcp.server import create_server

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "opendota" / "analysis.json").read_text()
)


class JourneyClient:
    def __init__(self) -> None:
        self.data = deepcopy(FIXTURE)
        self.calls = 0
        base = self.data["details"]["2001"]
        self.data["team_matches"] = []
        self.data["details"] = {}
        for value in range(3):
            match_id = 4000 + value
            detail = deepcopy(base)
            detail["match_id"] = match_id
            detail["start_time"] -= value
            self.data["details"][str(match_id)] = detail
            self.data["team_matches"].append(
                {"match_id": match_id, "start_time": detail["start_time"], "duration": 1300}
            )

    async def get_team(self, _team_id: int) -> dict[str, Any]:
        self.calls += 1
        return self.data["team"]

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
        return self.data["details"][str(match_id)]


@pytest.mark.asyncio
async def test_offline_first_page_and_continuation_preserve_context_without_io() -> None:
    fake = JourneyClient()
    registry = SnapshotRegistry(token_factory=iter(["first", "second"]).__next__)
    async with Client(create_server(client=fake, registry=registry)) as session:  # type: ignore[arg-type]
        first = (
            await session.call_tool(
                "analyze_pro_team_drafts",
                {"team_id": 1, "page_size": 1, "include": ["draft"]},
            )
        ).structured_content
        calls = fake.calls
        second = (
            await session.call_tool(
                "analyze_pro_team_drafts", {"continuation_cursor": first["next_cursor"]}
            )
        ).structured_content
        third = (
            await session.call_tool(
                "analyze_pro_team_drafts", {"continuation_cursor": second["next_cursor"]}
            )
        ).structured_content
    assert fake.calls == calls
    assert first["team"] == second["team"] == third["team"]
    assert first["filters"] == second["filters"] == third["filters"]
    assert first["coverage"] == second["coverage"] == third["coverage"]
    assert [page["matches"][0]["match_id"] for page in (first, second, third)] == [
        4000,
        4001,
        4002,
    ]
    assert "next_cursor" not in third
