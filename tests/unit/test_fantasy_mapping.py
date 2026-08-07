from __future__ import annotations

from datetime import date

import regex

from open_dota_mcp.models.fantasy import PlayerFantasyRequest, ProfessionalPlayerReference
from open_dota_mcp.services.fantasy import map_fantasy_match, map_raw_stats


def player_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "account_id": 101,
        "player_slot": 0,
        "hero_id": 25,
        "kills": 8,
        "deaths": 2,
        "assists": 14,
        "last_hits": 312,
        "denies": 18,
        "gold_per_min": 668,
        "tower_kills": 2,
        "obs_placed": 1,
        "camps_stacked": 3,
        "rune_pickups": 5,
        "item_uses": {"smoke_of_deceit": 0, "madstone_bundle": 99},
        "ability_uses": {"ability_lamp_use": 99},
        "roshans_killed": 0,
        "stuns": 42.75,
        "couriers_killed": 0,
        "firstblood_claimed": False,
    }
    row.update(updates)
    return row


def detail(**updates: object) -> dict[str, object]:
    row = player_row()
    enemy = {"account_id": 201, "player_slot": 128, "firstblood_claimed": True}
    value: dict[str, object] = {
        "match_id": 9001,
        "version": 21,
        "start_time": 1783000000,
        "duration": 2216,
        "patch": 61,
        "leagueid": 10,
        "league": {"name": "The International 2026", "tier": "premium"},
        "series_id": 501,
        "radiant_team_id": 1,
        "dire_team_id": 2,
        "radiant_name": "Radiant Pro",
        "dire_name": "Dire Pro",
        "radiant_win": True,
        "radiant_score": 31,
        "dire_score": 22,
        "players": [row, enemy],
        "objectives": [{"type": "CHAT_MESSAGE_MINIBOSS_KILL", "player_slot": 0, "team": 2}],
    }
    value.update(updates)
    return value


def test_compact_context_direct_stats_proxies_and_tormentor() -> None:
    evidence = map_fantasy_match(
        detail(),
        summary={"match_id": 9001, "leagueid": 10},
        player=ProfessionalPlayerReference(account_id=101, pro_name="Example"),
        patch_names={61: "7.41"},
        league_refs={10: ("The International 2026", "premium")},
        hero_refs={25: "Lina"},
        pattern=regex.compile("7\\.41"),
        request=PlayerFantasyRequest(account_id=101, version_pattern="7\\.41"),
        include_scoring=True,
    )
    assert evidence is not None
    assert evidence.context.result == "win"
    assert (evidence.context.team_kills, evidence.context.opponent_kills) == (31, 22)
    assert evidence.raw_stats.madstones_collected is None
    assert evidence.raw_stats.watchers_captured is None
    assert evidence.raw_stats.smoke_of_deceit_uses == 0
    assert evidence.raw_stats.first_blood is False
    assert evidence.raw_stats.tormentor_last_hits == 1
    assert len(evidence.fantasy_scoring.emblems) == 18  # type: ignore[union-attr]


def test_professional_provenance_and_filters_fail_closed() -> None:
    common = {
        "summary": {"match_id": 9001, "leagueid": 10},
        "player": ProfessionalPlayerReference(account_id=101, pro_name="Example"),
        "patch_names": {61: "7.41"},
        "league_refs": {10: ("TI", "premium")},
        "hero_refs": {25: "Lina"},
        "pattern": regex.compile("7\\.41"),
        "request": PlayerFantasyRequest(account_id=101, tournament_tiers=["all"]),
        "include_scoring": False,
    }
    assert map_fantasy_match(detail(leagueid=0), **common) is None
    assert (
        map_fantasy_match(detail(), **{**common, "summary": {"match_id": 9001, "leagueid": 11}})
        is None
    )
    dated = PlayerFantasyRequest(account_id=101, start_date=date(2027, 1, 1))
    assert map_fantasy_match(detail(), **{**common, "request": dated}) is None


def test_null_zero_false_and_incomplete_tormentor_attribution() -> None:
    row = player_row(kills=0, assists=0, firstblood_claimed=False)
    raw = detail(players=[row, {"account_id": 201, "player_slot": 128}], radiant_score=0)
    stats, warnings = map_raw_stats(raw, row, raw["players"], True, 0, "7.41")  # type: ignore[arg-type]
    assert stats.kills == 0
    assert stats.teamfight_participation is None
    assert stats.first_blood is None
    assert warnings[0].code == "team_kills_zero"
    raw["objectives"] = [{"type": "CHAT_MESSAGE_MINIBOSS_KILL", "team": 2}]
    stats, _ = map_raw_stats(raw, row, raw["players"], True, 1, "7.41")  # type: ignore[arg-type]
    assert stats.tormentor_last_hits is None


def test_first_blood_accepts_nullable_opendota_integer_flags() -> None:
    credited = player_row(firstblood_claimed=1)
    other = {"account_id": 201, "player_slot": 128, "firstblood_claimed": 0}
    raw = detail(players=[credited, other])
    stats, _ = map_raw_stats(raw, credited, raw["players"], True, 1, "7.41")  # type: ignore[arg-type]
    assert stats.first_blood is True

    not_credited = player_row(firstblood_claimed=0)
    credited_other = {"account_id": 201, "player_slot": 128, "firstblood_claimed": 1}
    raw = detail(players=[not_credited, credited_other])
    stats, _ = map_raw_stats(
        raw,
        not_credited,
        raw["players"],
        True,
        1,
        "7.41",  # type: ignore[arg-type]
    )
    assert stats.first_blood is False


def test_first_blood_rejects_malformed_flags() -> None:
    selected = player_row(firstblood_claimed=0)
    malformed = {"account_id": 201, "player_slot": 128, "firstblood_claimed": "1"}
    raw = detail(players=[selected, malformed])
    stats, _ = map_raw_stats(raw, selected, raw["players"], True, 1, "7.41")  # type: ignore[arg-type]
    assert stats.first_blood is None
