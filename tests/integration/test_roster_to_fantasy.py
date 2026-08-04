from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from open_dota_mcp.server import create_server


class JourneyClient:
    def __init__(self, *, mismatch: bool = False) -> None:
        self.mismatch = mismatch
        self.match_calls: list[int] = []

    async def get_team(self, team_id: int) -> dict[str, Any]:
        return {"team_id": team_id, "name": "Radiant Pro"}

    async def get_team_players(self, _team_id: int) -> list[dict[str, Any]]:
        return [{"account_id": value, "is_current_team_member": True} for value in range(101, 106)]

    async def get_team_matches(self, _team_id: int) -> list[dict[str, Any]]:
        return [{"match_id": 100, "start_time": 1783000000}]

    async def get_pro_players(self) -> list[dict[str, Any]]:
        return [{"account_id": value, "name": f"Player {value}"} for value in range(101, 107)]

    async def get_patches(self) -> list[dict[str, Any]]:
        return [{"id": 61, "name": "7.41", "date": 1782864000}]

    async def get_leagues(self) -> list[dict[str, Any]]:
        return [{"leagueid": 10, "name": "TI 2026", "tier": "premium"}]

    async def get_heroes(self) -> list[dict[str, Any]]:
        return [{"id": 25, "localized_name": "Lina"}]

    async def get_player_matches(
        self, account_id: int, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        return [] if offset else [{"match_id": 200 + account_id, "start_time": 1783000200}]

    async def get_match(self, match_id: int) -> dict[str, Any]:
        self.match_calls.append(match_id)
        if match_id == 100:
            observed = [101, 102, 103, 104, 106 if self.mismatch else 105]
            return {
                "match_id": 100,
                "version": 21,
                "start_time": 1783000000,
                "radiant_team_id": 1,
                "dire_team_id": 2,
                "players": [
                    {
                        "account_id": account_id,
                        "player_slot": index,
                        "lane_role": [1, 2, 3, 3, 1][index],
                        "times": [0, 600],
                        "lh_t": [0, [80, 55, 70, 20, 10][index]],
                    }
                    for index, account_id in enumerate(observed)
                ],
            }
        account_id = match_id - 200
        return {
            "match_id": match_id,
            "version": 21,
            "start_time": 1783000200,
            "duration": 1800,
            "patch": 61,
            "leagueid": 10,
            "league": {"name": "TI 2026", "tier": "premium"},
            "radiant_team_id": 1,
            "dire_team_id": 2,
            "radiant_name": "Radiant Pro",
            "dire_name": "Dire Pro",
            "radiant_win": True,
            "radiant_score": 10,
            "dire_score": 5,
            "players": [
                {
                    "account_id": account_id,
                    "player_slot": 0,
                    "hero_id": 25,
                    "kills": 4,
                    "deaths": 1,
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
                    "stuns": 0.0,
                    "couriers_killed": 0,
                    "firstblood_claimed": True,
                }
            ],
            "objectives": [],
        }


@pytest.mark.asyncio
async def test_team_to_five_ids_to_player_fantasy_in_one_session() -> None:
    async with Client(create_server(client=JourneyClient())) as session:  # type: ignore[arg-type]
        roster = (await session.call_tool("get_pro_team_roster", {"team_id": 1})).structured_content
        account_ids = [item["account_id"] for item in roster["players"]]
        fantasy = (
            await session.call_tool(
                "get_pro_player_fantasy",
                {"account_id": account_ids[0], "include": ["fantasy_scoring"]},
            )
        ).structured_content
    assert account_ids == [101, 102, 103, 104, 105]
    assert fantasy["player"]["account_id"] == 101
    assert fantasy["matches"][0]["context"]["player"]["account_id"] == 101
    assert "quality" not in str(fantasy) and "loadout" not in str(fantasy)


@pytest.mark.asyncio
async def test_lineup_mismatch_stops_without_older_search_or_positions() -> None:
    fake = JourneyClient(mismatch=True)
    async with Client(create_server(client=fake)) as session:  # type: ignore[arg-type]
        roster = (await session.call_tool("get_pro_team_roster", {"team_id": 1})).structured_content
    assert roster["error"]["code"] == "lineup_mismatch"
    assert "players" not in roster and fake.match_calls == [100]
