from __future__ import annotations

import pytest

from open_dota_mcp.services.identity import (
    load_team_catalog,
    normalize_identity,
    normalize_player_name,
    professional_by_account_id,
    resolve_league,
    resolve_professional_player,
    resolve_team,
)


def test_professional_player_normalization_exact_collisions_and_order() -> None:
    players = [
        {"account_id": 12, "name": "Ｔｅｓｔ--Player"},
        {"account_id": 11, "name": "Test Player"},
        {"account_id": 20, "name": "Test Pilot"},
    ]
    assert normalize_player_name("  TEST…PLAYER ") == "test player"
    collision = resolve_professional_player("test player", players)
    assert collision.selected is None
    assert [item["account_id"] for item in collision.candidates] == [11, 12]
    unique = resolve_professional_player("test pilot", players)
    assert unique.selected == players[2]
    assert resolve_professional_player("!!!", players).query == ""
    assert professional_by_account_id(20, players) == players[2]


def test_professional_player_candidates_are_bounded_to_ten() -> None:
    players = [{"account_id": value, "name": f"Same {value:02d}"} for value in range(1, 20)]
    result = resolve_professional_player("same", players)
    assert result.selected is None
    assert len(result.candidates) == 10
    assert [item["account_id"] for item in result.candidates] == list(range(1, 11))


def test_normalization_handles_unicode_case_and_punctuation() -> None:
    assert normalize_identity(" TÉAM—Spirit!! ") == "team spirit"


def test_unique_exact_league_is_preferred() -> None:
    leagues = [
        {"leagueid": 1, "name": "Dream League"},
        {"leagueid": 2, "name": "Dream League Season Two"},
    ]
    assert resolve_league("dream-league", leagues).selected == leagues[0]


def test_ranked_league_candidates_are_deterministic_and_bounded() -> None:
    leagues = [{"leagueid": value, "name": f"Cup {value}"} for value in range(20)]
    candidates = resolve_league("cup", leagues).candidates
    assert len(candidates) == 10
    assert [item["leagueid"] for item in candidates] == list(range(10))


def test_team_exact_tag_and_recency_tie_breaking() -> None:
    teams = [
        {"team_id": 1, "name": "One", "tag": "ABC", "last_match_time": 1},
        {"team_id": 2, "name": "ABC Team", "tag": "XYZ", "last_match_time": 5},
    ]
    candidates = resolve_team("a", teams).candidates
    assert [item["team_id"] for item in candidates] == [2, 1]
    assert resolve_team("abc", teams).selected == teams[0]
    assert resolve_team("xyz", teams).selected == teams[1]
    assert resolve_team(" ", teams).candidates == []


@pytest.mark.asyncio
async def test_team_catalog_rejects_repeated_nonempty_page() -> None:
    class Client:
        async def get_teams_page(self, _page: int) -> list[dict[str, int]]:
            return [{"team_id": 1}]

    with pytest.raises(ValueError, match="repeated"):
        await load_team_catalog(Client())  # type: ignore[arg-type]
