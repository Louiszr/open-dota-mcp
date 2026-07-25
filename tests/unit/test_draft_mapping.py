from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from open_dota_mcp.services.drafts import map_match_draft


def complete_match() -> dict[str, object]:
    return {
        "match_id": 1001,
        "start_time": 1784779200,
        "patch": 60,
        "leagueid": 10,
        "radiant_team_id": 1,
        "radiant_name": "Radiant Pro",
        "dire_team_id": 2,
        "dire_name": "Dire Pro",
        "radiant_win": True,
        "radiant_score": 31,
        "dire_score": 22,
        "duration": 2400,
        "series_id": 8,
        "series_type": 1,
        "league": {"name": "DreamLeague"},
        "picks_bans": [
            {"is_pick": True, "hero_id": 1, "team": 1, "order": 1},
            {"is_pick": False, "hero_id": 14, "team": 0, "order": 0},
        ],
        "players": [
            {
                "hero_id": 1,
                "player_slot": 128,
                "account_id": 42,
                "name": "Pro Name",
                "personaname": "Never Expose",
            }
        ],
        "draft_timings": [
            {"order": 0, "extra_time": 0, "total_time_taken": 12},
            {"order": 1, "extra_time": 3, "total_time_taken": 18},
        ],
        "unknown_future_field": {"large": "ignored"},
    }


def mapped(raw: dict[str, object], include: set[str] | None = None):
    return map_match_draft(
        raw,
        heroes={1: "Anti-Mage", 14: "Pudge"},
        patches={60: "7.41"},
        professionals={42: "Catalog Name"},
        include=include or set(),
        retrieved_at=datetime(2026, 7, 23, tzinfo=UTC),
    )


def test_authoritative_order_source_index_and_pick_only_player_mapping() -> None:
    draft = mapped(complete_match())
    assert [action.order for action in draft.draft_actions] == [0, 1]
    assert [action.source_index for action in draft.draft_actions] == [1, 0]
    assert draft.draft_actions[0].player is None
    assert draft.draft_actions[1].player.professional_name == "Pro Name"
    assert draft.match_date.isoformat() == "2026-07-23"
    assert "unknown_future_field" not in draft.model_dump()


def test_degraded_order_retains_full_upstream_sequence_and_supplied_values() -> None:
    raw = complete_match()
    raw["picks_bans"][1]["order"] = 1  # type: ignore[index]
    draft = mapped(raw)
    assert draft.ordering_quality == "degraded"
    assert [action.source_index for action in draft.draft_actions] == [0, 1]
    assert [action.order for action in draft.draft_actions] == [1, 1]
    assert draft.warnings[0].code == "degraded_draft_order"


def test_professional_catalog_then_steam32_fallback_never_persona() -> None:
    raw = complete_match()
    raw["players"][0]["name"] = None  # type: ignore[index]
    draft = mapped(raw)
    assert draft.draft_actions[1].player.professional_name == "Catalog Name"

    raw["players"][0]["account_id"] = 99  # type: ignore[index]
    fallback = mapped(raw).draft_actions[1].player
    assert fallback.display_identity == 99
    assert fallback.identity_source == "steam32_fallback"
    assert "Never Expose" not in str(fallback.model_dump())


def test_ambiguous_same_side_mapping_is_not_guessed() -> None:
    raw = complete_match()
    raw["players"].append(deepcopy(raw["players"][0]))  # type: ignore[union-attr,index]
    player = mapped(raw).draft_actions[1].player
    assert player.identity_source == "ambiguous"
    assert player.account_id is None


def test_timing_and_all_additive_groups_are_independent() -> None:
    for group in ("competition", "result", "draft_timing", "provenance"):
        payload = mapped(complete_match(), {group}).model_dump()
        if group == "draft_timing":
            assert payload["draft_actions"][0]["timing"]["extra_time_seconds"] == 0
        else:
            assert group in payload
    all_groups = mapped(
        complete_match(), {"competition", "result", "draft_timing", "provenance"}
    ).model_dump()
    assert all_groups["result"]["winner"] == "radiant"
    assert all_groups["competition"]["league_id"] == 10
    assert all_groups["provenance"]["source"] == "OpenDota"


def test_missing_labels_and_timing_emit_localized_nonempty_warnings() -> None:
    draft = map_match_draft(
        complete_match(),
        heroes={},
        patches={},
        professionals={},
        include={"draft_timing"},
        retrieved_at=datetime.now(UTC),
    )
    assert draft.completeness == "partial"
    assert draft.warnings
    assert all(action.warnings for action in draft.draft_actions)
