"""Lean public models for team-relative drafting analysis."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_serializer, model_validator

from open_dota_mcp.errors import AnalysisErrorDetail, SparseModel, omit_none
from open_dota_mcp.models.common import Side, TeamResult, utc_iso


class TournamentTier(StrEnum):
    """Supported upstream league tiers."""

    PREMIUM = "premium"
    PROFESSIONAL = "professional"
    AMATEUR = "amateur"
    ALL = "all"


class FirstBanFilter(StrEnum):
    """Team-relative first-ban selector."""

    YES = "yes"
    NO = "no"


class BanOrder(StrEnum):
    """Known team-relative ban order."""

    FIRST = "first"
    SECOND = "second"


class AnalysisInclude(StrEnum):
    """Additive report evidence groups."""

    DRAFT = "draft"
    LANES = "lanes"
    ECONOMY = "economy"
    STRUCTURES = "structures"
    OBJECTIVES = "objectives"


class DraftingReportRequest(SparseModel):
    """Normalized first-page report request."""

    team_id: int = Field(gt=0)
    lookback_count: int = Field(default=25, ge=1, le=100)
    version_pattern: str | None = Field(default=None, max_length=64)
    tournament_tiers: list[TournamentTier] = Field(default_factory=lambda: [TournamentTier.PREMIUM])
    side: Side | None = None
    result: TeamResult | None = None
    first_ban: FirstBanFilter | None = None
    include: list[AnalysisInclude] = Field(default_factory=list)
    page_size: int = Field(default=10, ge=1, le=25)


class TeamReference(SparseModel):
    """Stable team lookup identity without a tag."""

    team_id: int = Field(gt=0)
    name: str


class TournamentReference(SparseModel):
    """Public tournament name and upstream tier."""

    name: str
    tier: str


class AppliedFilters(SparseModel):
    """Resolved report filters without diagnostic state."""

    patch: str
    tournament_tiers: list[str]
    side: Side | None = Field(default=None, exclude_if=omit_none)
    result: TeamResult | None = Field(default=None, exclude_if=omit_none)
    first_ban: FirstBanFilter | None = Field(default=None, exclude_if=omit_none)


class LookbackCoverage(SparseModel):
    """Aggregate parse coverage for the completed-match quota."""

    examined: int = Field(ge=0, le=100)
    parsed: int = Field(ge=0)
    unparsed: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_partition(self) -> LookbackCoverage:
        """Require parsed and unparsed counts to partition examined matches."""
        if self.parsed + self.unparsed != self.examined:
            raise ValueError("parsed plus unparsed must equal examined")
        return self


class DraftMatchup(SparseModel):
    """Opposing heroes known for one picked hero at action time."""

    known: bool
    lane: Literal["safelane", "midlane", "offlane"]
    opposing_heroes: list[str]


class AnalysisDraftAction(SparseModel):
    """One compact chronological draft action."""

    order: int = Field(ge=0)
    type: Literal["pick", "ban"]
    round: int | None = Field(default=None, ge=1, exclude_if=omit_none)
    team: str
    hero: str
    player: str | None = Field(default=None, exclude_if=omit_none)
    matchup: DraftMatchup | None = Field(default=None, exclude_if=omit_none)


class DraftEvidence(SparseModel):
    """Chronological draft evidence group."""

    actions: list[AnalysisDraftAction]


class LaneComparison(SparseModel):
    """One team-relative lane comparison at ten minutes."""

    lane: Literal["safelane", "midlane", "offlane"]
    analyzed_team_heroes: list[str]
    opponent_heroes: list[str]
    experience_difference_10: int | None = None
    last_hit_difference_10: int | None = None


class LaneEvidence(SparseModel):
    """Available lane comparisons."""

    lanes: list[LaneComparison]


class HeroTotalGold(SparseModel):
    """Per-hero total earned gold observations."""

    hero: str
    player: str | None = Field(default=None, exclude_if=omit_none)
    team: str
    at_10: int | None = None
    at_20: int | None = None


class HeroExperience(SparseModel):
    """Per-hero experience observations."""

    hero: str
    player: str | None = Field(default=None, exclude_if=omit_none)
    team: str
    at_10: int | None = None
    at_20: int | None = None


class EconomyEvidence(SparseModel):
    """Team-relative and per-hero supported economy facts."""

    gold_difference_10: int | None = None
    gold_difference_20: int | None = None
    experience_difference_10: int | None = None
    experience_difference_20: int | None = None
    hero_total_gold: list[HeroTotalGold]
    hero_experience: list[HeroExperience]


class StructureCheckpoints(SparseModel):
    """Cumulative lost structure keys at report checkpoints."""

    by_10: list[str] | None = None
    by_20: list[str] | None = None


class StructureEvidence(SparseModel):
    """Attributed structure losses for both teams."""

    analyzed_team_lost: StructureCheckpoints
    opponent_lost: StructureCheckpoints


class ObjectiveTeamEvidence(SparseModel):
    """Attributed objective event times through 25 minutes."""

    roshan_by_25: list[int] | None = None
    tormentor_by_25: list[int] | None = None


class ObjectiveEvidence(SparseModel):
    """Objective event ledgers for both teams."""

    analyzed_team: ObjectiveTeamEvidence
    opponent: ObjectiveTeamEvidence


class MatchComparison(SparseModel):
    """Lean parsed match outcome with requested evidence groups."""

    match_id: int = Field(gt=0)
    start_time: datetime
    duration_seconds: int = Field(ge=0)
    tournament: TournamentReference
    patch: str
    analyzed_team: str
    opponent: TeamReference
    side: Side
    result: TeamResult
    ban_order: BanOrder | None = None
    draft: DraftEvidence | None = Field(default=None, exclude_if=omit_none)
    lanes: LaneEvidence | None = Field(default=None, exclude_if=omit_none)
    economy: EconomyEvidence | None = Field(default=None, exclude_if=omit_none)
    structures: StructureEvidence | None = Field(default=None, exclude_if=omit_none)
    objectives: ObjectiveEvidence | None = Field(default=None, exclude_if=omit_none)

    @field_serializer("start_time")
    def serialize_start_time(self, value: datetime) -> str:
        """Serialize match starts in canonical UTC form."""
        return utc_iso(value)


class DraftingReport(SparseModel):
    """One page of an immutable drafting report."""

    team: TeamReference
    filters: AppliedFilters
    coverage: LookbackCoverage
    matches: list[MatchComparison]
    next_cursor: str | None = Field(default=None, exclude_if=omit_none)


class AnalysisToolResponse(SparseModel):
    """Success report or concise public error."""

    team: TeamReference | None = Field(default=None, exclude_if=omit_none)
    filters: AppliedFilters | None = Field(default=None, exclude_if=omit_none)
    coverage: LookbackCoverage | None = Field(default=None, exclude_if=omit_none)
    matches: list[MatchComparison] | None = Field(default=None, exclude_if=omit_none)
    next_cursor: str | None = Field(default=None, exclude_if=omit_none)
    error: AnalysisErrorDetail | None = Field(default=None, exclude_if=omit_none)

    @classmethod
    def from_report(cls, report: DraftingReport) -> AnalysisToolResponse:
        """Build the tool envelope from a successful report page."""
        return cls(**report.model_dump())
