from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from open_dota_mcp.errors import AnalysisErrorDetail, UpstreamError
from open_dota_mcp.models.analysis import (
    AnalysisToolResponse,
    AppliedFilters,
    DraftEvidence,
    DraftingReport,
    EconomyEvidence,
    LaneEvidence,
    LookbackCoverage,
    MatchComparison,
    ObjectiveEvidence,
    ObjectiveTeamEvidence,
    StructureCheckpoints,
    StructureEvidence,
    TeamReference,
    TournamentReference,
)


def core_match() -> MatchComparison:
    return MatchComparison(
        match_id=1,
        start_time=datetime(2026, 7, 1, tzinfo=UTC),
        duration_seconds=1200,
        tournament=TournamentReference(name="Cup", tier="premium"),
        patch="7.41",
        analyzed_team="Radiant Pro",
        opponent=TeamReference(team_id=2, name="Dire Pro"),
        side="radiant",
        result="win",
        ban_order=None,
    )


def test_retry_exhaustion_has_only_safe_analysis_details() -> None:
    error = UpstreamError(
        "upstream_rate_limited",
        "OpenDota rate-limit recovery exhausted the delay budget",
        retry_exhausted=True,
        reason="delay_budget",
        retry_after_seconds=38.2,
    ).analysis_detail()
    assert error.model_dump() == {
        "code": "upstream_rate_limited",
        "message": "OpenDota rate-limit recovery exhausted the delay budget",
        "reason": "delay_budget",
        "retry_after_seconds": 38.2,
    }


def test_coverage_partition_and_enum_validation_are_enforced() -> None:
    assert LookbackCoverage(examined=3, parsed=2, unparsed=1)
    with pytest.raises(ValidationError, match="parsed plus unparsed"):
        LookbackCoverage(examined=3, parsed=1, unparsed=1)
    with pytest.raises(ValidationError):
        core_match().model_copy(update={"side": "middle"}, deep=True).__class__.model_validate(
            {**core_match().model_dump(), "side": "middle"}
        )
    with pytest.raises(ValidationError):
        DraftEvidence(
            actions=[
                {
                    "order": 0,
                    "type": "trade",
                    "round": 1,
                    "team": "Radiant Pro",
                    "hero": "Lina",
                }
            ]
        )


def test_slim_report_serialization_omits_all_unrequested_groups_and_prohibited_fields() -> None:
    report = DraftingReport(
        team=TeamReference(team_id=1, name="Radiant Pro"),
        filters=AppliedFilters(patch="7.41", tournament_tiers=["premium"]),
        coverage=LookbackCoverage(examined=1, parsed=1, unparsed=0),
        matches=[core_match()],
    )
    payload = report.model_dump(mode="json")
    assert set(payload) == {"team", "filters", "coverage", "matches"}
    assert set(payload["matches"][0]) == {
        "match_id",
        "start_time",
        "duration_seconds",
        "tournament",
        "patch",
        "analyzed_team",
        "opponent",
        "side",
        "result",
        "ban_order",
    }
    prohibited = {"source", "provenance", "quality", "reason", "warnings", "league_id"}
    assert prohibited.isdisjoint(str(payload))


def test_all_evidence_groups_are_independently_additive_and_preserve_null_empty_semantics() -> None:
    match = core_match()
    match.draft = DraftEvidence(actions=[])
    match.lanes = LaneEvidence(lanes=[])
    match.economy = EconomyEvidence(
        gold_difference_10=None, gold_difference_20=0, hero_total_gold=[]
    )
    match.structures = StructureEvidence(
        analyzed_team_lost=StructureCheckpoints(by_10=[], by_20=None),
        opponent_lost=StructureCheckpoints(by_10=[], by_20=[]),
    )
    match.objectives = ObjectiveEvidence(
        analyzed_team=ObjectiveTeamEvidence(roshan_by_25=[], tormentor_by_25=None),
        opponent=ObjectiveTeamEvidence(roshan_by_25=[], tormentor_by_25=[]),
    )
    payload = match.model_dump(mode="json")
    assert payload["economy"]["gold_difference_10"] is None
    assert payload["economy"]["gold_difference_20"] == 0
    assert payload["structures"]["analyzed_team_lost"] == {"by_10": [], "by_20": None}
    assert payload["objectives"]["analyzed_team"]["tormentor_by_25"] is None


def test_analysis_tool_error_has_no_success_fields() -> None:
    payload = AnalysisToolResponse(
        error=AnalysisErrorDetail(code="invalid_team_id", message="Use a positive stable team ID")
    ).model_dump()
    assert payload == {
        "error": {"code": "invalid_team_id", "message": "Use a positive stable team ID"}
    }
