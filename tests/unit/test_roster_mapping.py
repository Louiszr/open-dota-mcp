from __future__ import annotations

import pytest
from pydantic import ValidationError

from open_dota_mcp.models.roster import LineupCoverage, TeamRosterRequest
from open_dota_mcp.services.roster import _current_members, _team_rows, infer_positions


def lineup_rows(*, tie: bool = False, malformed: bool = False) -> list[dict[str, object]]:
    rows = [
        {"account_id": 101, "player_slot": 0, "lane_role": 1, "times": [0, 600], "lh_t": [0, 82]},
        {"account_id": 102, "player_slot": 1, "lane_role": 2, "times": [0, 600], "lh_t": [0, 60]},
        {
            "account_id": 103,
            "player_slot": 2,
            "lane_role": 3,
            "times": [0, 590, 600],
            "lh_t": [0, 65, 70],
        },
        {
            "account_id": 104,
            "player_slot": 3,
            "lane_role": 3,
            "times": [0, 600],
            "lh_t": [0, 20 if not tie else 70],
        },
        {"account_id": 105, "player_slot": 4, "lane_role": 1, "times": [0, 600], "lh_t": [0, 12]},
    ]
    if malformed:
        rows[4]["lane_role"] = 4
    return rows


def test_roster_selector_and_coverage_bounds() -> None:
    assert TeamRosterRequest(team_id=1).team_id == 1
    for values in ({}, {"team_id": 1, "team_name": "x"}, {"team_name": "  "}):
        with pytest.raises(ValidationError):
            TeamRosterRequest.model_validate(values)
    with pytest.raises(ValidationError):
        LineupCoverage(completed_records_considered=6, details_requested=0, parsed_usable=0)


def test_clean_position_inference_and_deterministic_order() -> None:
    players, warnings = infer_positions(
        lineup_rows(), {value: f"Player {value}" for value in range(101, 106)}
    )
    assert warnings == []
    assert [item.account_id for item in players] == [101, 102, 103, 104, 105]
    assert [item.position for item in players] == [1, 2, 3, 4, 5]
    assert players[2].last_hits_at_10 == 70


@pytest.mark.parametrize("kwargs", [{"tie": True}, {"malformed": True}])
def test_ambiguous_evidence_never_invents_positions(kwargs: dict[str, bool]) -> None:
    players, warnings = infer_positions(lineup_rows(**kwargs), {})
    assert warnings[0].code == "position_ambiguous"
    assert any(item.position is None for item in players)
    assert all(
        item.inference_status == ("inferred" if item.position else "ambiguous") for item in players
    )


def test_missing_farm_keeps_only_supported_mid_position() -> None:
    rows = lineup_rows()
    rows[0].pop("lh_t")
    players, warnings = infer_positions(rows, {})
    by_id = {item.account_id: item for item in players}
    assert by_id[102].position == 2
    assert by_id[101].position is None and by_id[105].position is None
    assert warnings[0].code == "position_ambiguous"


def test_current_membership_requires_five_strict_true_values() -> None:
    valid = [
        {"account_id": account_id, "is_current_team_member": True} for account_id in range(101, 106)
    ]
    assert _current_members(valid) == set(range(101, 106))
    for invalid_flag in (False, None, 1, "true"):
        records = [dict(item) for item in valid]
        records[0]["is_current_team_member"] = invalid_flag
        assert _current_members(records) is None
    assert _current_members([*valid, valid[0]]) is None


def test_requested_team_side_must_be_unique_with_exactly_five_ids() -> None:
    detail = {
        "version": 21,
        "radiant_team_id": 1,
        "dire_team_id": 2,
        "players": lineup_rows(),
    }
    assert len(_team_rows(detail, 1) or []) == 5
    assert _team_rows({**detail, "dire_team_id": 1}, 1) is None
    assert _team_rows(detail, 3) is None
    duplicated = lineup_rows()
    duplicated[-1]["account_id"] = 101
    assert _team_rows({**detail, "players": duplicated}, 1) is None
