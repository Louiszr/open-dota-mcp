from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from open_dota_mcp.server import create_server


class JourneyClient:
    async def get_leagues(self) -> list[dict[str, Any]]:
        return [
            {"leagueid": 10, "name": "DreamLeague 30", "tier": "premium"},
            {"leagueid": 11, "name": "DreamLeague 29", "tier": "professional"},
        ]

    async def get_league_matches(self, league_id: int) -> list[dict[str, Any]]:
        return [self.summary()] if league_id == 10 else []

    async def get_teams_page(self, page: int) -> list[dict[str, Any]]:
        return (
            [
                {"team_id": 1, "name": "Team Spirit", "tag": "TS", "last_match_time": 5},
                {"team_id": 2, "name": "Team Secret", "tag": "TS", "last_match_time": 4},
            ]
            if page == 0
            else []
        )

    async def get_team(self, team_id: int) -> dict[str, Any]:
        return {"team_id": team_id, "name": "Team Spirit", "tag": "TS"}

    async def get_team_matches(self, _team_id: int) -> list[dict[str, Any]]:
        return [
            {
                "match_id": 1001,
                "start_time": 1784779200,
                "leagueid": 10,
                "league_name": "DreamLeague 30",
                "radiant": True,
                "opposing_team_id": 2,
                "opposing_team_name": "Team Secret",
                "radiant_win": True,
                "radiant_score": 30,
                "dire_score": 20,
            }
        ]

    async def get_heroes(self) -> list[dict[str, Any]]:
        return [{"id": 14, "localized_name": "Pudge"}]

    async def get_patches(self) -> list[dict[str, Any]]:
        return [{"id": 60, "name": "7.41"}]

    async def get_pro_players(self) -> list[dict[str, Any]]:
        return []

    async def get_match(self, match_id: int) -> dict[str, Any]:
        return {
            **self.summary(),
            "match_id": match_id,
            "patch": 60,
            "radiant_name": "Team Spirit",
            "dire_name": "Team Secret",
            "picks_bans": [{"is_pick": False, "hero_id": 14, "team": 0, "order": 0}],
        }

    async def aclose(self) -> None:
        return None

    @staticmethod
    def summary() -> dict[str, Any]:
        return {
            "match_id": 1001,
            "start_time": 1784779200,
            "leagueid": 10,
            "league_name": "DreamLeague 30",
            "radiant_team_id": 1,
            "radiant_team_name": "Team Spirit",
            "dire_team_id": 2,
            "dire_team_name": "Team Secret",
            "radiant_win": True,
            "radiant_score": 30,
            "dire_score": 20,
        }


@pytest.mark.asyncio
async def test_exactly_six_typed_tools_and_known_id_two_call_flow() -> None:
    async with Client(create_server(client=JourneyClient())) as session:  # type: ignore[arg-type]
        tools = await session.list_tools()
        assert [tool.name for tool in tools] == [
            "get_pro_match_drafts",
            "list_pro_tournament_matches",
            "list_pro_team_matches",
            "analyze_pro_team_drafts",
            "get_pro_player_fantasy",
            "get_pro_team_roster",
        ]
        assert all(tool.description and tool.inputSchema["type"] == "object" for tool in tools)
        discovery = await session.call_tool("list_pro_tournament_matches", {"league_id": 10})
        match_id = (
            discovery.structured_content["match_id"]
            if "match_id" in discovery.structured_content
            else 1001
        )
        draft = await session.call_tool("get_pro_match_drafts", {"match_ids": [match_id]})
        payload = draft.structured_content
        assert payload["matches"][0]["draft"]["match_id"] == 1001
        assert "warnings" not in payload["matches"][0]["draft"]


@pytest.mark.asyncio
async def test_ambiguous_tournament_and_team_three_call_journeys() -> None:
    async with Client(create_server(client=JourneyClient())) as session:  # type: ignore[arg-type]
        tournament = await session.call_tool(
            "list_pro_tournament_matches", {"tournament_name": "dreamleague"}
        )
        tournament_payload = tournament.structured_content
        assert tournament_payload["warnings"][0]["status"] == "needs_selection"
        selected = await session.call_tool("list_pro_tournament_matches", {"league_id": 10})
        assert selected.structured_content["matches"][0]["match_id"] == 1001

        team = await session.call_tool("list_pro_team_matches", {"team_name": "TS"})
        assert len(team.structured_content["candidates"]) == 2
        selected_team = await session.call_tool("list_pro_team_matches", {"team_id": 1})
        match_id = selected_team.structured_content["matches"][0]["match_id"]
        draft = await session.call_tool("get_pro_match_drafts", {"match_ids": [match_id]})
        assert draft.structured_content["matches"][0]["draft"]
