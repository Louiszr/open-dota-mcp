"""Typed models for latest-observed professional team lineups."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_serializer, field_validator, model_validator

from open_dota_mcp.errors import (
    DataWarning,
    SparseModel,
    ToolErrorDetail,
    omit_none,
    omit_none_or_empty,
)
from open_dota_mcp.models.common import utc_iso


class TeamRosterRequest(SparseModel):
    """Exactly one professional-team selector."""

    team_id: int | None = Field(default=None, gt=0)
    team_name: str | None = Field(default=None, max_length=200)

    @field_validator("team_name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        """Reject blank names."""
        if value is not None and not value.strip():
            raise ValueError("team_name must not be blank")
        return value

    @model_validator(mode="after")
    def validate_selector(self) -> TeamRosterRequest:
        """Require exactly one selector."""
        if (self.team_id is None) == (self.team_name is None):
            raise ValueError("provide exactly one of team_id or team_name")
        return self


class RosterTeamReference(SparseModel):
    """Resolved team identity."""

    team_id: int = Field(gt=0)
    name: str


class RosterTeamCandidate(RosterTeamReference):
    """Bounded selection candidate with optional tag."""

    tag: str | None = Field(default=None, exclude_if=omit_none)


class LineupSourceMatch(SparseModel):
    """Professional map that supplied observed lineup evidence."""

    match_id: int = Field(gt=0)
    start_time: datetime

    @field_serializer("start_time")
    def serialize_start_time(self, value: datetime) -> str:
        """Serialize source time in canonical UTC form."""
        return utc_iso(value)


class LineupCoverage(SparseModel):
    """Fixed five-record lineup scan accounting."""

    completed_records_considered: int = Field(ge=0, le=5)
    details_requested: int = Field(ge=0, le=5)
    parsed_usable: int = Field(ge=0, le=1)


class LineupPlayer(SparseModel):
    """Cross-checked player ID with conservative match-derived position evidence."""

    account_id: int = Field(gt=0)
    pro_name: str | None = None
    position: int | None = Field(default=None, ge=1, le=5)
    lane: Literal["safelane", "midlane", "offlane"] | None = None
    last_hits_at_10: int | None = Field(default=None, ge=0)
    inference_status: Literal["inferred", "ambiguous"]


class LatestObservedLineupResponse(SparseModel):
    """Verified five-player lineup, bounded candidates, or cannot-infer outcome."""

    team: RosterTeamReference | None = Field(default=None, exclude_if=omit_none)
    source_match: LineupSourceMatch | None = Field(default=None, exclude_if=omit_none)
    coverage: LineupCoverage | None = Field(default=None, exclude_if=omit_none)
    players: list[LineupPlayer] | None = Field(default=None, exclude_if=omit_none_or_empty)
    candidates: list[RosterTeamCandidate] | None = Field(
        default=None, exclude_if=omit_none_or_empty
    )
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)
    error: ToolErrorDetail | None = Field(default=None, exclude_if=omit_none)

    @model_validator(mode="after")
    def validate_players(self) -> LatestObservedLineupResponse:
        """Require exactly five players on successful lineup results."""
        if self.players is not None and len(self.players) != 5:
            raise ValueError("a lineup must contain exactly five players")
        return self
