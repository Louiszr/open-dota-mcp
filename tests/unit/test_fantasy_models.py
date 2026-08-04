from __future__ import annotations

import json
import math
from copy import deepcopy

import pytest
from pydantic import ValidationError

from open_dota_mcp.fantasy_rules import (
    EMBLEM_RULES,
    score_raw_stats,
    score_rule,
    validate_scoring_reference,
)
from open_dota_mcp.models.fantasy import FantasyRawStats, PlayerFantasyRequest
from open_dota_mcp.resources import load_ti_2026_scoring


def raw_stats(**updates: object) -> FantasyRawStats:
    values = {
        "kills": 8,
        "deaths": 2,
        "assists": 14,
        "last_hits": 312,
        "denies": 18,
        "gold_per_minute": 668,
        "madstones_collected": None,
        "tower_last_hits": 2,
        "observer_wards_placed": 1,
        "camps_stacked": 3,
        "runes_picked_up_or_bottled": 5,
        "watchers_captured": None,
        "lotuses_taken": None,
        "smoke_of_deceit_uses": 0,
        "roshan_last_hits": 0,
        "teamfight_participation": 22 / 31,
        "stun_duration_seconds": 42.75,
        "tormentor_last_hits": 1,
        "courier_last_hits": 0,
        "first_blood": False,
    }
    values.update(updates)
    return FantasyRawStats.model_validate(values)


def test_request_validation_and_bounds() -> None:
    request = PlayerFantasyRequest(account_id=101)
    assert request.match_count == 20
    assert request.tournament_tiers == ["premium"]
    for values in (
        {},
        {"account_id": 1, "player_name": "x"},
        {"account_id": 1, "match_count": 0},
        {"account_id": 1, "match_count": 101},
        {"account_id": 1, "tournament_tiers": ["all", "premium"]},
        {"account_id": 1, "include": ["fantasy_scoring", "fantasy_scoring"]},
    ):
        with pytest.raises(ValidationError):
            PlayerFantasyRequest.model_validate(values)


def test_all_eighteen_formulas_and_null_zero_false_semantics() -> None:
    scores = {score.key: score.raw_points for score in score_raw_stats(raw_stats())}
    assert len(scores) == 18
    assert scores == {
        "kills": 856,
        "deaths": 1560,
        "creep_score": 990,
        "gpm": 1336,
        "madstone": None,
        "tower_kills": 704,
        "wards_placed": 117,
        "camps_stacked": 702,
        "runes_grabbed": 705,
        "watchers_taken": None,
        "lotuses_grabbed": None,
        "smokes_used": 0,
        "roshan_kills": 0,
        "teamfight_participation": pytest.approx(1507.3548387096773),
        "stuns": 427.5,
        "tormentor_kills": 879,
        "courier_kills": 0,
        "first_blood": 0,
    }
    assert score_raw_stats(raw_stats(deaths=99))[1].raw_points == 0
    assert score_raw_stats(raw_stats(first_blood=None))[-1].raw_points is None


def test_nonfinite_formula_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        score_rule(EMBLEM_RULES[0], {"kills": math.inf})
    with pytest.raises(ValidationError):
        raw_stats(stun_duration_seconds=math.nan)


def test_installed_reference_schema_inventory_and_parity() -> None:
    content = load_ti_2026_scoring()
    document = validate_scoring_reference(content)
    assert document["edition"] == "ti-2026-v1"
    assert [item["multiplier"] for item in document["quality_tiers"]] == [1.1, 1.3, 1.6, 2.0, 2.5]
    assert {item["name"] for item in document["traits"]} == {
        "Fractal",
        "Friendly",
        "Vampiric",
        "Unique",
        "Benevolent",
    }
    assert len(document["titles"]) == 16
    assert document["projection_semantics"]["result_label"] == "counterfactual_projection"
    assert json.loads(content) == document


def test_reference_rejects_numeric_unknown_effect() -> None:
    document = json.loads(load_ti_2026_scoring())
    document["traits"][0]["numeric_effect"] = 0.5
    with pytest.raises(ValueError, match="unknown effects"):
        validate_scoring_reference(document)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(edition="wrong"), "edition metadata"),
        (lambda value: value.update(retrieved_at="not-a-date"), "ISO calendar"),
        (lambda value: value["emblems"].pop(), "exactly 18"),
        (
            lambda value: value["emblems"][0].update(inputs=["not_a_raw_field"]),
            "canonical formulas",
        ),
        (lambda value: value["quality_tiers"][0].update(order=2), "multipliers"),
        (lambda value: value["traits"][0].pop("scope"), "documented schema"),
        (lambda value: value["titles"][0].update(component="suffix"), "title inventory"),
        (lambda value: value["sources"][0].update(url="http://insecure"), "HTTPS"),
        (lambda value: value["aggregation"].pop("unknown_series"), "aggregation rules"),
        (
            lambda value: value["projection_semantics"].update(result_label="observed"),
            "projection semantics",
        ),
    ],
)
def test_reference_rejects_schema_and_semantic_drift(mutate, message: str) -> None:
    document = deepcopy(json.loads(load_ti_2026_scoring()))
    mutate(document)
    with pytest.raises(ValueError, match=message):
        validate_scoring_reference(document)


def test_reference_exact_modifier_evidence_and_aggregation_rules() -> None:
    document = validate_scoring_reference(load_ti_2026_scoring())
    effects = {item["name"]: item for item in [*document["traits"], *document["titles"]]}
    assert effects["Unique"]["numeric_effect"] == 0.3
    assert effects["Unique"]["status"] == "community_verified"
    assert effects["the Underdog"]["numeric_effect"] == 0.06
    assert all(
        item["numeric_effect"] is None
        for name, item in effects.items()
        if name not in {"Unique", "the Underdog"}
    )
    assert "two highest-scoring maps" in document["aggregation"]["series_map_selection"]
    assert "greatest confirmed-series sum" in document["aggregation"]["stage_selection"]
    assert all(item["status"] != "official" for item in document["emblems"])
