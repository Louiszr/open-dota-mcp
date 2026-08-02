from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from open_dota_mcp.pagination import SnapshotRegistry
from open_dota_mcp.services.analysis import (
    AnalysisService,
    AnalysisValidationError,
    map_match_comparison,
    normalize_completed_matches,
    normalize_request,
)
from open_dota_mcp.services.drafts import (
    authoritative_draft_actions,
    draft_action_rounds,
    hero_lane_opponents,
    unique_player_for_hero,
)

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "opendota" / "analysis.json").read_text()
)


class AnalysisClient:
    def __init__(self) -> None:
        self.data = deepcopy(FIXTURE)
        self.detail_calls = 0
        self.active = 0
        self.maximum_active = 0

    async def get_team(self, team_id: int) -> dict[str, Any]:
        return self.data["team"] if team_id == 1 else {}

    async def get_patches(self) -> list[dict[str, Any]]:
        return self.data["patches"]

    async def get_team_matches(self, _team_id: int) -> list[dict[str, Any]]:
        return self.data["team_matches"]

    async def get_leagues(self) -> list[dict[str, Any]]:
        return self.data["leagues"]

    async def get_heroes(self) -> list[dict[str, Any]]:
        return self.data["heroes"]

    async def get_pro_players(self) -> list[dict[str, Any]]:
        return self.data["pro_players"]

    async def get_match(self, match_id: int) -> dict[str, Any]:
        self.detail_calls += 1
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        return self.data["details"][str(match_id)]


def request(**overrides: Any):
    values = {
        "team_id": 1,
        "lookback_count": None,
        "version_pattern": None,
        "tournament_tiers": None,
        "side": None,
        "result": None,
        "first_ban": None,
        "include": None,
        "page_size": None,
    }
    values.update(overrides)
    return normalize_request(**values)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"team_id": 0}, "invalid_team_id"),
        ({"lookback_count": 101}, "invalid_lookback_count"),
        ({"version_pattern": "("}, "invalid_version_expression"),
        ({"version_pattern": "x" * 65}, "invalid_version_expression"),
        ({"tournament_tiers": []}, "invalid_tournament_tiers"),
        ({"tournament_tiers": ["all", "premium"]}, "invalid_tournament_tiers"),
        ({"include": ["draft", "draft"]}, "invalid_include"),
        ({"page_size": 26}, "invalid_page_size"),
        ({"side": "middle"}, "invalid_filter"),
    ],
)
def test_request_validation_is_classified(overrides: dict[str, Any], code: str) -> None:
    with pytest.raises(AnalysisValidationError) as caught:
        request(**overrides)
    assert caught.value.detail.code == code


def test_expression_boundary_and_full_string_semantics() -> None:
    normalized, pattern = request(version_pattern="x" * 64)
    assert normalized.version_pattern == "x" * 64
    assert pattern is not None and pattern.fullmatch("x" * 64, timeout=0.05)
    _, pattern = request(version_pattern=r"7[.]4[01]")
    assert pattern is not None and pattern.fullmatch("7.41", timeout=0.05)
    assert pattern.fullmatch("prefix-7.41", timeout=0.05) is None


def test_completed_match_quota_is_newest_first_deduplicated_before_filters() -> None:
    normalized = normalize_completed_matches(FIXTURE["team_matches"])
    assert [value["match_id"] for value in normalized] == [2002, 2001, 2003, 2004]


@pytest.mark.asyncio
async def test_default_selection_coverage_core_projection_and_five_request_bound() -> None:
    fake = AnalysisClient()
    response = await AnalysisService(fake, SnapshotRegistry()).analyze(team_id=1)  # type: ignore[arg-type]
    payload = response.model_dump(mode="json")
    assert payload["filters"] == {"patch": "7.41", "tournament_tiers": ["premium"]}
    assert payload["coverage"] == {"examined": 4, "parsed": 2, "unparsed": 2}
    assert len(payload["matches"]) == 1
    assert payload["matches"][0]["opponent"] == {"team_id": 2, "name": "Dire Pro"}
    assert fake.detail_calls == 4 and fake.maximum_active <= 5


@pytest.mark.asyncio
async def test_latest_patch_selection_accepts_realistic_iso_release_dates() -> None:
    fake = AnalysisClient()
    fake.data["patches"][0]["date"] = "2023-04-27T00:00:00.000Z"
    fake.data["patches"][1]["date"] = "2025-07-01T00:00:00.000Z"
    fake.data["patches"][2]["date"] = "2026-07-01T00:00:00.000Z"
    response = await AnalysisService(fake, SnapshotRegistry()).analyze(team_id=1)  # type: ignore[arg-type]
    assert response.filters is not None and response.filters.patch == "7.41"


@pytest.mark.asyncio
async def test_scenario_filters_are_team_relative_conjunctive_and_unknown_is_excluded() -> None:
    fake = AnalysisClient()
    response = await AnalysisService(fake, SnapshotRegistry()).analyze(  # type: ignore[arg-type]
        team_id=1,
        version_pattern=r"7[.]4[01]",
        tournament_tiers=["all"],
        side="dire",
        result="loss",
        first_ban="no",
    )
    assert [value.match_id for value in response.matches or []] == [2003]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"side": "radiant"}, [2001]),
        ({"side": "dire"}, [2003]),
        ({"result": "win"}, [2001]),
        ({"result": "loss"}, [2003]),
        ({"first_ban": "yes"}, [2001]),
        ({"first_ban": "no"}, [2003]),
    ],
)
async def test_each_scenario_filter_has_a_team_relative_truth_table(
    filters: dict[str, str], expected: list[int]
) -> None:
    response = await AnalysisService(AnalysisClient(), SnapshotRegistry()).analyze(  # type: ignore[arg-type]
        team_id=1,
        version_pattern=r"7[.]4[01]",
        tournament_tiers=["all"],
        **filters,
    )
    assert [value.match_id for value in response.matches or []] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("placement", ["neither", "both"])
async def test_anomalous_team_placement_is_excluded_but_remains_parsed_coverage(
    placement: str,
) -> None:
    fake = AnalysisClient()
    raw = deepcopy(fake.data["details"]["2001"])
    raw["match_id"] = 6001
    if placement == "neither":
        raw["radiant_team_id"], raw["dire_team_id"] = 2, 3
    else:
        raw["radiant_team_id"], raw["dire_team_id"] = 1, 1
    fake.data["details"] = {"6001": raw}
    fake.data["team_matches"] = [
        {"match_id": 6001, "start_time": raw["start_time"], "duration": raw["duration"]}
    ]
    response = await AnalysisService(fake, SnapshotRegistry()).analyze(team_id=1)  # type: ignore[arg-type]
    assert response.coverage is not None
    assert response.coverage.model_dump() == {"examined": 1, "parsed": 1, "unparsed": 0}
    assert response.matches == []


@pytest.mark.asyncio
async def test_unknown_ban_order_cannot_satisfy_either_first_ban_filter() -> None:
    for requested in ("yes", "no"):
        fake = AnalysisClient()
        raw = deepcopy(fake.data["details"]["2001"])
        raw["picks_bans"][1]["order"] = raw["picks_bans"][0]["order"]
        fake.data["details"] = {"2001": raw}
        fake.data["team_matches"] = [fake.data["team_matches"][1]]
        response = await AnalysisService(fake, SnapshotRegistry()).analyze(  # type: ignore[arg-type]
            team_id=1, first_ban=requested
        )
        assert response.matches == []
        assert response.coverage is not None and response.coverage.parsed == 1


@pytest.mark.asyncio
async def test_optional_reference_failures_remain_sparse_and_do_not_destroy_core_report() -> None:
    class SparseReferenceClient(AnalysisClient):
        async def get_leagues(self) -> list[dict[str, Any]]:
            raise RuntimeError("league catalog unavailable")

        async def get_heroes(self) -> list[dict[str, Any]]:
            raise RuntimeError("hero catalog unavailable")

        async def get_pro_players(self) -> list[dict[str, Any]]:
            raise RuntimeError("player catalog unavailable")

    response = await AnalysisService(  # type: ignore[arg-type]
        SparseReferenceClient(), SnapshotRegistry()
    ).analyze(team_id=1, include=["draft"])
    assert response.error is None
    assert response.matches and response.matches[0].match_id == 2001
    assert response.matches[0].draft is not None
    assert response.matches[0].draft.actions == []


def test_evidence_mapping_uses_team_perspective_rounds_checkpoints_and_attribution() -> None:
    raw = deepcopy(FIXTURE["details"]["2001"])
    raw["objectives"][2]["team"] = 2
    raw["objectives"][3]["team"] = 3
    match = map_match_comparison(
        raw,
        summary=FIXTURE["team_matches"][1],
        team_id=1,
        patch_names={58: "7.33", 60: "7.40", 61: "7.41"},
        patch_dates={58: 1682553600, 60: 1751328000, 61: 1782864000},
        league_refs={10: ("Premier Cup", "premium")},
        hero_names={value["id"]: value["localized_name"] for value in FIXTURE["heroes"]},
        professional_names={value["account_id"]: value["name"] for value in FIXTURE["pro_players"]},
        include={"draft", "lanes", "economy", "structures", "objectives"},
    )
    assert match is not None
    assert [action.round for action in match.draft.actions] == [1, 1, 1, 1]  # type: ignore[union-attr]
    lina = match.draft.actions[-1]  # type: ignore[union-attr]
    assert lina.player == "MidPlayer" and lina.matchup.opposing_heroes == ["Storm Spirit"]
    lane = match.lanes.lanes[0]  # type: ignore[union-attr]
    assert lane.experience_difference_10 == 300 and lane.last_hit_difference_10 == 6
    assert match.economy.gold_difference_10 == 400  # type: ignore[union-attr]
    assert match.economy.gold_difference_20 == -200  # type: ignore[union-attr]
    assert match.economy.experience_difference_10 == 300  # type: ignore[union-attr]
    assert match.economy.experience_difference_20 == -500  # type: ignore[union-attr]
    assert [
        (item.hero, item.team, item.at_10, item.at_20)
        for item in match.economy.hero_experience  # type: ignore[union-attr]
    ] == [
        ("Lina", "Radiant Pro", 4000, 9000),
        ("Storm Spirit", "Dire Pro", 3700, 8500),
    ]
    assert match.structures.analyzed_team_lost.by_10 == ["top_t1"]  # type: ignore[union-attr]
    assert match.objectives.analyzed_team.roshan_by_25 == [900]  # type: ignore[union-attr]
    assert match.objectives.opponent.tormentor_by_25 == [1250]  # type: ignore[union-attr]


def test_evidence_is_symmetric_for_the_opposing_team_perspective() -> None:
    raw = deepcopy(FIXTURE["details"]["2001"])
    match = map_match_comparison(
        raw,
        summary=FIXTURE["team_matches"][1],
        team_id=2,
        patch_names={58: "7.33", 61: "7.41"},
        patch_dates={58: 1682553600, 61: 1782864000},
        league_refs={10: ("Premier Cup", "premium")},
        hero_names={value["id"]: value["localized_name"] for value in FIXTURE["heroes"]},
        professional_names={value["account_id"]: value["name"] for value in FIXTURE["pro_players"]},
        include={"lanes", "economy", "structures", "objectives"},
    )
    assert match is not None and match.side == "dire" and match.result == "loss"
    assert match.lanes.lanes[0].experience_difference_10 == -300  # type: ignore[union-attr]
    assert match.economy.gold_difference_10 == -400  # type: ignore[union-attr]
    assert match.economy.gold_difference_20 == 200  # type: ignore[union-attr]
    assert match.economy.experience_difference_10 == -300  # type: ignore[union-attr]
    assert match.economy.experience_difference_20 == 500  # type: ignore[union-attr]
    assert match.structures.analyzed_team_lost.by_20 == ["mid_t1"]  # type: ignore[union-attr]
    assert match.structures.opponent_lost.by_10 == ["top_t1"]  # type: ignore[union-attr]
    assert match.objectives.analyzed_team.tormentor_by_25 == [1250]  # type: ignore[union-attr]
    assert match.objectives.opponent.roshan_by_25 == [900]  # type: ignore[union-attr]


def test_short_matches_and_unattributed_events_preserve_null_and_empty_semantics() -> None:
    raw = deepcopy(FIXTURE["details"]["2001"])
    raw["duration"] = 500
    raw["objectives"] = [
        {"type": "building_kill", "time": 100, "key": "unknown_building"},
        {"type": "CHAT_MESSAGE_ROSHAN_KILL", "time": 100},
    ]
    match = map_match_comparison(
        raw,
        summary=FIXTURE["team_matches"][1],
        team_id=1,
        patch_names={58: "7.33", 61: "7.41"},
        patch_dates={58: 1682553600, 61: 1782864000},
        league_refs={10: ("Premier Cup", "premium")},
        hero_names={value["id"]: value["localized_name"] for value in FIXTURE["heroes"]},
        professional_names={},
        include={"lanes", "economy", "structures", "objectives"},
    )
    assert match is not None
    assert match.lanes.lanes[0].experience_difference_10 is None  # type: ignore[union-attr]
    assert match.economy.gold_difference_10 is None  # type: ignore[union-attr]
    assert match.economy.experience_difference_10 is None  # type: ignore[union-attr]
    assert match.economy.hero_total_gold[0].at_10 is None  # type: ignore[union-attr]
    assert match.economy.hero_experience[0].at_10 is None  # type: ignore[union-attr]
    assert match.structures.analyzed_team_lost.by_10 is None  # type: ignore[union-attr]
    assert match.objectives.analyzed_team.roshan_by_25 == []  # type: ignore[union-attr]
    assert match.objectives.opponent.roshan_by_25 == []  # type: ignore[union-attr]


def test_economy_experience_preserves_zero_partial_and_missing_without_reconstruction() -> None:
    raw = deepcopy(FIXTURE["details"]["2001"])
    raw["radiant_xp_adv"][10] = 0
    raw["radiant_xp_adv"][20] = None
    raw["players"][0]["xp_t"] = [0, 3900, 4000]
    raw["players"][1].pop("xp_t")
    match = map_match_comparison(
        raw,
        summary=FIXTURE["team_matches"][1],
        team_id=1,
        patch_names={61: "7.41"},
        patch_dates={61: 1782864000},
        league_refs={10: ("Premier Cup", "premium")},
        hero_names={value["id"]: value["localized_name"] for value in FIXTURE["heroes"]},
        professional_names={},
        include={"economy"},
    )
    assert match is not None and match.economy is not None
    assert match.economy.experience_difference_10 == 0
    assert match.economy.experience_difference_20 is None
    assert match.economy.hero_experience[0].at_10 == 4000
    assert match.economy.hero_experience[0].at_20 == 4000
    assert match.economy.hero_experience[1].at_10 is None
    assert match.economy.hero_experience[1].at_20 is None


def test_economy_does_not_reconstruct_missing_team_experience_from_complete_heroes() -> None:
    raw = deepcopy(FIXTURE["details"]["2001"])
    raw.pop("radiant_xp_adv")
    match = map_match_comparison(
        raw,
        summary=FIXTURE["team_matches"][1],
        team_id=1,
        patch_names={61: "7.41"},
        patch_dates={61: 1782864000},
        league_refs={10: ("Premier Cup", "premium")},
        hero_names={value["id"]: value["localized_name"] for value in FIXTURE["heroes"]},
        professional_names={},
        include={"economy"},
    )
    assert match is not None and match.economy is not None
    assert match.economy.experience_difference_10 is None
    assert match.economy.experience_difference_20 is None
    assert [(item.at_10, item.at_20) for item in match.economy.hero_experience] == [
        (4000, 9000),
        (3700, 8500),
    ]


def test_ambiguous_chronology_and_player_mapping_are_omitted_not_guessed() -> None:
    raw = deepcopy(FIXTURE["details"]["2001"])
    raw["picks_bans"][1]["order"] = 0
    raw["players"].append(deepcopy(raw["players"][0]))
    match = map_match_comparison(
        raw,
        summary=FIXTURE["team_matches"][1],
        team_id=1,
        patch_names={61: "7.41"},
        patch_dates={61: 1782864000},
        league_refs={10: ("Premier Cup", "premium")},
        hero_names={value["id"]: value["localized_name"] for value in FIXTURE["heroes"]},
        professional_names={},
        include={"draft"},
    )
    assert match is not None and match.ban_order is None
    assert all(action.round is None for action in match.draft.actions)  # type: ignore[union-attr]
    assert match.draft.actions[-1].player is None  # type: ignore[union-attr]


def test_reusable_draft_chronology_round_player_and_lane_helpers() -> None:
    raw = deepcopy(FIXTURE["details"]["2001"])
    ordered, authoritative = authoritative_draft_actions(raw)
    assert authoritative and [value["order"] for value in ordered] == [0, 1, 2, 3]
    assert [draft_action_rounds(ordered)[id(value)] for value in ordered] == [1, 1, 1, 1]
    players = raw["players"]
    lina = unique_player_for_hero(players, 1, "radiant")
    assert lina is players[0]
    assert hero_lane_opponents(players, "radiant", 2) == [players[1]]
    players.append(deepcopy(players[0]))
    assert unique_player_for_hero(players, 1, "radiant") is None
