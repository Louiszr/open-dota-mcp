"""Canonical typed TI 2026 fantasy formulas and resource validation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from open_dota_mcp.models.fantasy import FantasyRawStats, RawEmblemScore


class FormulaOperation(StrEnum):
    """Safe supported fantasy formula operations."""

    MULTIPLY = "multiply"
    SUM_MULTIPLY = "sum_multiply"
    DEATH_FLOOR = "death_floor"
    BOOLEAN_AWARD = "boolean_award"


@dataclass(frozen=True, slots=True)
class EmblemRule:
    """Canonical formula metadata for one emblem."""

    key: str
    display_name: str
    color: Literal["red", "blue", "green"]
    inputs: tuple[str, ...]
    operation: FormulaOperation
    parameters: dict[str, int | float]


EMBLEM_RULES: tuple[EmblemRule, ...] = (
    EmblemRule("kills", "Kills", "red", ("kills",), FormulaOperation.MULTIPLY, {"factor": 107}),
    EmblemRule(
        "deaths",
        "Deaths",
        "red",
        ("deaths",),
        FormulaOperation.DEATH_FLOOR,
        {"maximum": 1950, "penalty": 195, "floor": 0},
    ),
    EmblemRule(
        "creep_score",
        "Creep Score",
        "red",
        ("last_hits", "denies"),
        FormulaOperation.SUM_MULTIPLY,
        {"factor": 3},
    ),
    EmblemRule("gpm", "GPM", "red", ("gold_per_minute",), FormulaOperation.MULTIPLY, {"factor": 2}),
    EmblemRule(
        "madstone",
        "Madstone",
        "red",
        ("madstones_collected",),
        FormulaOperation.MULTIPLY,
        {"factor": 13},
    ),
    EmblemRule(
        "tower_kills",
        "Tower Kills",
        "red",
        ("tower_last_hits",),
        FormulaOperation.MULTIPLY,
        {"factor": 352},
    ),
    EmblemRule(
        "wards_placed",
        "Wards Placed",
        "blue",
        ("observer_wards_placed",),
        FormulaOperation.MULTIPLY,
        {"factor": 117},
    ),
    EmblemRule(
        "camps_stacked",
        "Camps Stacked",
        "blue",
        ("camps_stacked",),
        FormulaOperation.MULTIPLY,
        {"factor": 234},
    ),
    EmblemRule(
        "runes_grabbed",
        "Runes Grabbed",
        "blue",
        ("runes_picked_up_or_bottled",),
        FormulaOperation.MULTIPLY,
        {"factor": 141},
    ),
    EmblemRule(
        "watchers_taken",
        "Watchers Taken",
        "blue",
        ("watchers_captured",),
        FormulaOperation.MULTIPLY,
        {"factor": 147},
    ),
    EmblemRule(
        "lotuses_grabbed",
        "Lotuses Grabbed",
        "blue",
        ("lotuses_taken",),
        FormulaOperation.MULTIPLY,
        {"factor": 176},
    ),
    EmblemRule(
        "smokes_used",
        "Smokes Used",
        "blue",
        ("smoke_of_deceit_uses",),
        FormulaOperation.MULTIPLY,
        {"factor": 293},
    ),
    EmblemRule(
        "roshan_kills",
        "Roshan Kills",
        "green",
        ("roshan_last_hits",),
        FormulaOperation.MULTIPLY,
        {"factor": 1172},
    ),
    EmblemRule(
        "teamfight_participation",
        "Teamfight Participation",
        "green",
        ("teamfight_participation",),
        FormulaOperation.MULTIPLY,
        {"factor": 2124},
    ),
    EmblemRule(
        "stuns",
        "Stuns",
        "green",
        ("stun_duration_seconds",),
        FormulaOperation.MULTIPLY,
        {"factor": 10},
    ),
    EmblemRule(
        "tormentor_kills",
        "Tormentor Kills",
        "green",
        ("tormentor_last_hits",),
        FormulaOperation.MULTIPLY,
        {"factor": 879},
    ),
    EmblemRule(
        "courier_kills",
        "Courier Kills",
        "green",
        ("courier_last_hits",),
        FormulaOperation.MULTIPLY,
        {"factor": 703},
    ),
    EmblemRule(
        "first_blood",
        "First Blood",
        "green",
        ("first_blood",),
        FormulaOperation.BOOLEAN_AWARD,
        {"award": 1934},
    ),
)


def score_rule(
    rule: EmblemRule, inputs: dict[str, int | float | bool | None]
) -> int | float | None:
    """Evaluate one typed formula without executing expression text.

    Args:
        rule: Canonical emblem rule.
        inputs: Raw values for exactly the rule's required inputs.

    Returns:
        Pre-modifier points or ``None`` when any input is unavailable.

    Raises:
        ValueError: If an input is nonnumeric, boolean where numeric, or nonfinite.
    """
    values = [inputs.get(name) for name in rule.inputs]
    if any(value is None for value in values):
        return None
    if rule.operation is FormulaOperation.BOOLEAN_AWARD:
        if not isinstance(values[0], bool):
            raise ValueError("boolean_award requires a boolean")
        return rule.parameters["award"] if values[0] else 0
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise ValueError("numeric fantasy inputs must be numbers")
    numbers = [float(value) for value in values]
    if not all(math.isfinite(value) and value >= 0 for value in numbers):
        raise ValueError("fantasy inputs must be finite and nonnegative")
    if rule.operation is FormulaOperation.MULTIPLY:
        result = numbers[0] * rule.parameters["factor"]
    elif rule.operation is FormulaOperation.SUM_MULTIPLY:
        result = sum(numbers) * rule.parameters["factor"]
    else:
        result = max(
            rule.parameters["floor"],
            rule.parameters["maximum"] - rule.parameters["penalty"] * numbers[0],
        )
    return int(result) if result.is_integer() else result


def score_raw_stats(stats: FantasyRawStats) -> list[RawEmblemScore]:
    """Calculate all 18 canonical scores from typed raw statistics."""
    raw = stats.model_dump()
    return [
        RawEmblemScore(
            key=rule.key,
            color=rule.color,
            inputs={name: raw[name] for name in rule.inputs},
            raw_points=score_rule(rule, {name: raw[name] for name in rule.inputs}),
        )
        for rule in EMBLEM_RULES
    ]


def validate_scoring_reference(payload: str | bytes | dict[str, Any]) -> dict[str, Any]:
    """Validate installed scoring data against canonical formulas and evidence rules.

    Args:
        payload: JSON text/bytes or decoded mapping.

    Returns:
        The validated decoded document.

    Raises:
        ValueError: If schema, inventory, source, or formula parity is invalid.
    """
    document = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    if not isinstance(document, dict):
        raise ValueError("scoring reference must be a JSON object")
    required = {
        "edition",
        "competition",
        "effective_date",
        "retrieved_at",
        "raw_score_definition",
        "emblems",
        "quality_tiers",
        "traits",
        "titles",
        "aggregation",
        "projection_semantics",
        "sources",
        "caveats",
    }
    if not required <= document.keys():
        raise ValueError("scoring reference is missing required sections")
    if document["edition"] != "ti-2026-v1" or document["competition"] != "The International 2026":
        raise ValueError("scoring reference edition metadata is invalid")
    try:
        date.fromisoformat(document["retrieved_at"])
        if document["effective_date"] is not None:
            date.fromisoformat(document["effective_date"])
    except (TypeError, ValueError) as exc:
        raise ValueError("scoring reference dates must be ISO calendar dates") from exc
    if (
        not isinstance(document["raw_score_definition"], str)
        or not document["raw_score_definition"].strip()
    ):
        raise ValueError("raw score definition must be nonblank")
    if not isinstance(document["emblems"], list) or len(document["emblems"]) != 18:
        raise ValueError("scoring reference must contain exactly 18 emblems")

    canonical = [
        {
            "key": rule.key,
            "color": rule.color,
            "inputs": list(rule.inputs),
            "operation": rule.operation.value,
            "parameters": rule.parameters,
        }
        for rule in EMBLEM_RULES
    ]
    actual = [
        {key: item.get(key) for key in ("key", "color", "inputs", "operation", "parameters")}
        for item in document["emblems"]
    ]
    if actual != canonical:
        raise ValueError("resource emblems do not match canonical formulas")
    raw_fields = set(FantasyRawStats.model_fields)
    required_emblem = {
        "display_name",
        "unit",
        "formula",
        "status",
        "source_ids",
        "caveat",
    }
    for item, rule in zip(document["emblems"], EMBLEM_RULES, strict=True):
        if not required_emblem <= item.keys() or item["display_name"] != rule.display_name:
            raise ValueError("emblem documentation is incomplete")
        if item["status"] not in {"baseline", "community_verified"}:
            raise ValueError("emblem evidence status is invalid")
        if not set(item["inputs"]) <= raw_fields:
            raise ValueError("emblem inputs must map to documented raw statistics")
        if not item["source_ids"] or not str(item["caveat"]).strip():
            raise ValueError("emblems require sources and caveats")

    expected_tiers = [
        {"tier": tier, "multiplier": multiplier, "order": order}
        for order, (tier, multiplier) in enumerate(
            zip(("I", "II", "III", "IV", "V"), (1.1, 1.3, 1.6, 2.0, 2.5), strict=True),
            start=1,
        )
    ]
    if document["quality_tiers"] != expected_tiers:
        raise ValueError("quality tier multipliers are invalid")

    sources = document["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("scoring reference requires sources")
    source_ids = {item.get("id") for item in sources if isinstance(item, dict)}
    if len(source_ids) != len(sources) or None in source_ids:
        raise ValueError("scoring source IDs must be unique and nonblank")
    required_source = {"id", "title", "url", "publisher", "retrieved_at"}
    if any(
        not required_source <= item.keys()
        or not all(str(item[key]).strip() for key in required_source)
        or not str(item["url"]).startswith("https://")
        for item in sources
    ):
        raise ValueError("all scoring sources must be complete HTTPS records")

    facts = [*document["traits"], *document["titles"]]
    trait_names = {"Fractal", "Friendly", "Vampiric", "Unique", "Benevolent"}
    prefixes = {
        "Otherworldly",
        "Emerald",
        "Golden",
        "Heroic",
        "Cerulean",
        "Royal",
        "Crimson",
        "Elemental",
    }
    suffixes = {
        "the Tormented",
        "the Flayed Twins Acolyte",
        "the Patient",
        "the Underdog",
        "the Decisive",
        "the Clutch",
        "the Lucky",
        "the Cruel",
    }
    if {item.get("name") for item in document["traits"]} != trait_names:
        raise ValueError("trait inventory is incomplete")
    actual_prefixes = {
        item.get("name") for item in document["titles"] if item.get("component") == "prefix"
    }
    actual_suffixes = {
        item.get("name") for item in document["titles"] if item.get("component") == "suffix"
    }
    if actual_prefixes != prefixes or actual_suffixes != suffixes:
        raise ValueError("title inventory or components are incomplete")
    required_fact = {
        "name",
        "scope",
        "prerequisites",
        "application_order",
        "stacking",
        "numeric_effect",
        "status",
        "source_ids",
        "caveat",
    }
    if any(
        not required_fact <= item.keys()
        or item.get("status") not in {"official", "community_verified", "unknown"}
        or not isinstance(item.get("prerequisites"), list)
        or not item.get("source_ids")
        or not str(item.get("scope", "")).strip()
        or not str(item.get("application_order", "")).strip()
        or not str(item.get("stacking", "")).strip()
        or not str(item.get("caveat", "")).strip()
        for item in facts
    ):
        raise ValueError("modifier facts do not satisfy the documented schema")
    if any(
        item.get("status") == "unknown" and item.get("numeric_effect") is not None for item in facts
    ):
        raise ValueError("unknown effects must not be numeric")

    aggregation = document["aggregation"]
    required_aggregation = {
        "banner_contribution",
        "series_map_selection",
        "stage_selection",
        "unknown_series",
        "status",
        "source_ids",
    }
    if not isinstance(aggregation, dict) or not required_aggregation <= aggregation.keys():
        raise ValueError("aggregation rules are incomplete")
    if (
        "two highest-scoring maps" not in aggregation["series_map_selection"]
        or "greatest confirmed-series sum" not in aggregation["stage_selection"]
        or "null series IDs" not in aggregation["unknown_series"]
    ):
        raise ValueError("aggregation invariants are incomplete")

    if any(
        not set(item.get("source_ids", [])) <= source_ids
        for item in [*document["emblems"], *facts, aggregation]
    ):
        raise ValueError("scoring reference contains an unknown source ID")
    if len(document["traits"]) != 5 or len(document["titles"]) != 16:
        raise ValueError("scoring modifier inventory is incomplete")

    projection = document["projection_semantics"]
    required_projection = {
        "historical_evidence",
        "candidate_configuration",
        "result_label",
        "application_order",
        "unknown_effects",
    }
    expected_order = [
        "raw_score",
        "quality_multiplier",
        "trait_effects",
        "title_effects",
        "banner_aggregation",
        "series_aggregation",
    ]
    if (
        not isinstance(projection, dict)
        or not required_projection <= projection.keys()
        or projection["result_label"] != "counterfactual_projection"
        or projection["application_order"] != expected_order
        or "observed raw inputs" not in projection["historical_evidence"]
        or "never replaced by a guessed value" not in projection["unknown_effects"]
    ):
        raise ValueError("retrospective projection semantics are incomplete")
    if not isinstance(document["caveats"], list) or not document["caveats"]:
        raise ValueError("scoring reference requires caveats")
    return document
