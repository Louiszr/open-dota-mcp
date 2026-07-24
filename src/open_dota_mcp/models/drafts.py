"""Stable structured models for professional draft evidence."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field, field_serializer

from open_dota_mcp.errors import (
    DataWarning,
    SparseModel,
    ToolErrorDetail,
    omit_none,
    omit_none_or_empty,
)
from open_dota_mcp.models.common import HeroIdentity, PlayerIdentity, Side, TeamIdentity, utc_iso


class OrderingQuality(StrEnum):
    """Confidence in upstream draft chronology."""

    AUTHORITATIVE = "authoritative"
    DEGRADED = "degraded"


class Completeness(StrEnum):
    """Whether required labels and identities were available."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class ActionType(StrEnum):
    """Draft pick or ban action."""

    PICK = "pick"
    BAN = "ban"


class DraftTiming(SparseModel):
    """Optional timing context for one draft action."""

    extra_time_seconds: int | None = None
    total_time_taken_seconds: int | None = None


class DraftAction(SparseModel):
    """One retained upstream pick or ban action."""

    source_index: int = Field(ge=0)
    order: int | None = None
    action_type: ActionType
    acting_side: Side | None = None
    acting_team: TeamIdentity
    hero: HeroIdentity
    player: PlayerIdentity | None = None
    timing: DraftTiming | None = Field(default=None, exclude_if=omit_none)
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)


class Competition(SparseModel):
    """Optional tournament and series context."""

    league_id: int | None = None
    league_name: str | None = None
    series_id: int | None = None
    series_type: int | None = None


class MatchResult(SparseModel):
    """Optional match outcome context."""

    winner: str | None = None
    radiant_score: int | None = None
    dire_score: int | None = None
    duration_seconds: int | None = None


class Provenance(SparseModel):
    """Safe provenance without credential-bearing URLs."""

    retrieved_at: datetime
    source: str = "OpenDota"
    parse_version: int | None = None
    upstream_match_version: int | None = None
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)

    @field_serializer("retrieved_at")
    def serialize_retrieved_at(self, value: datetime) -> str:
        """Serialize retrieval time in canonical UTC form."""
        return utc_iso(value)


class MatchDraft(SparseModel):
    """Compact ordered professional draft evidence."""

    match_id: int = Field(gt=0)
    start_time: datetime | None = None
    match_date: date | None = None
    patch_id: int | None = None
    patch_version: str | None = None
    radiant_team: TeamIdentity
    dire_team: TeamIdentity
    ordering_quality: OrderingQuality
    completeness: Completeness
    draft_actions: list[DraftAction]
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)
    competition: Competition | None = Field(default=None, exclude_if=omit_none)
    result: MatchResult | None = Field(default=None, exclude_if=omit_none)
    provenance: Provenance | None = Field(default=None, exclude_if=omit_none)

    @field_serializer("start_time")
    def serialize_start_time(self, value: datetime | None) -> str | None:
        """Serialize match start in canonical UTC form."""
        return utc_iso(value) if value is not None else None


class DraftOutcome(SparseModel):
    """Sparse success or failure for one requested match."""

    match_id: int
    draft: MatchDraft | None = Field(default=None, exclude_if=omit_none)
    error: ToolErrorDetail | None = Field(default=None, exclude_if=omit_none)


class DraftResponse(SparseModel):
    """First-occurrence ordered batch draft response."""

    requested_match_ids: list[int]
    matches: list[DraftOutcome]


class DraftToolResponse(SparseModel):
    """Direct MCP draft success or validation-error envelope."""

    requested_match_ids: list[int] | None = Field(default=None, exclude_if=omit_none)
    matches: list[DraftOutcome] | None = Field(default=None, exclude_if=omit_none)
    error: ToolErrorDetail | None = Field(default=None, exclude_if=omit_none)
