"""Stable models for professional match discovery tools."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_serializer

from open_dota_mcp.errors import (
    DataWarning,
    SparseModel,
    ToolErrorDetail,
    omit_none,
    omit_none_or_empty,
)
from open_dota_mcp.models.common import (
    LeagueIdentity,
    PageMetadata,
    Side,
    TeamIdentity,
    TeamResult,
    Winner,
    utc_iso,
)


class LeagueCandidate(LeagueIdentity):
    """Bounded tournament identity candidate."""


class TeamCandidate(TeamIdentity):
    """Bounded team identity candidate with recency context."""

    team_id: int = Field(gt=0)
    last_match_time: datetime | None = None

    @field_serializer("last_match_time")
    def serialize_last_match(self, value: datetime | None) -> str | None:
        """Serialize recency in canonical UTC form."""
        return utc_iso(value) if value is not None else None


class TournamentMatchSummary(SparseModel):
    """Slim professional tournament match projection."""

    match_id: int
    start_time: datetime | None = None
    league: LeagueIdentity
    radiant_team: TeamIdentity
    dire_team: TeamIdentity
    winner: Winner | None = None
    radiant_score: int | None = None
    dire_score: int | None = None
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)

    @field_serializer("start_time")
    def serialize_start_time(self, value: datetime | None) -> str | None:
        """Serialize match start in canonical UTC form."""
        return utc_iso(value) if value is not None else None


class TeamMatchSummary(SparseModel):
    """Slim match projection relative to a selected team."""

    match_id: int
    start_time: datetime | None = None
    league: LeagueIdentity
    selected_team: TeamIdentity
    opponent: TeamIdentity
    selected_team_side: Side
    selected_team_result: TeamResult | None = None
    radiant_score: int | None = None
    dire_score: int | None = None
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)

    @field_serializer("start_time")
    def serialize_start_time(self, value: datetime | None) -> str | None:
        """Serialize match start in canonical UTC form."""
        return utc_iso(value) if value is not None else None


class TeamFilters(SparseModel):
    """Canonical echo of inclusive UTC and team-relative filters."""

    start_date: str | None = None
    end_date: str | None = None
    side: Side | None = None
    result: TeamResult | None = None


class TournamentResponse(SparseModel):
    """Tournament page, selection outcome, or error envelope."""

    league: LeagueIdentity | None = Field(default=None, exclude_if=omit_none)
    matches: list[TournamentMatchSummary] | None = Field(default=None, exclude_if=omit_none)
    page: PageMetadata | None = Field(default=None, exclude_if=omit_none)
    query: str | None = Field(default=None, exclude_if=omit_none)
    candidates: list[LeagueCandidate] | None = Field(default=None, exclude_if=omit_none_or_empty)
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)
    error: ToolErrorDetail | None = Field(default=None, exclude_if=omit_none)


class TeamResponse(SparseModel):
    """Team page, selection outcome, or error envelope."""

    team: TeamIdentity | None = Field(default=None, exclude_if=omit_none)
    filters: TeamFilters | None = Field(default=None, exclude_if=omit_none)
    matches: list[TeamMatchSummary] | None = Field(default=None, exclude_if=omit_none)
    page: PageMetadata | None = Field(default=None, exclude_if=omit_none)
    query: str | None = Field(default=None, exclude_if=omit_none)
    candidates: list[TeamCandidate] | None = Field(default=None, exclude_if=omit_none_or_empty)
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)
    error: ToolErrorDetail | None = Field(default=None, exclude_if=omit_none)
