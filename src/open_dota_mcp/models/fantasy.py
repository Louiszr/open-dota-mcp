"""Typed public models for TI 2026 professional fantasy evidence."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_serializer, field_validator, model_validator

from open_dota_mcp.errors import (
    DataWarning,
    SparseModel,
    ToolErrorDetail,
    omit_none,
    omit_none_or_empty,
)
from open_dota_mcp.models.analysis import TournamentTier
from open_dota_mcp.models.common import utc_iso


class FantasyInclude(StrEnum):
    """Supported additive fantasy response groups."""

    FANTASY_SCORING = "fantasy_scoring"


class PlayerFantasyRequest(SparseModel):
    """Validated first-page request for professional fantasy evidence."""

    account_id: int | None = Field(default=None, gt=0)
    player_name: str | None = Field(default=None, max_length=200)
    match_count: int = Field(default=20, ge=1, le=100)
    version_pattern: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    tournament_tiers: list[TournamentTier] = Field(default_factory=lambda: [TournamentTier.PREMIUM])
    include: list[FantasyInclude] = Field(default_factory=list)

    @field_validator("player_name")
    @classmethod
    def validate_player_name(cls, value: str | None) -> str | None:
        """Reject a blank player selector before upstream reads."""
        if value is not None and not value.strip():
            raise ValueError("player_name must not be blank")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> PlayerFantasyRequest:
        """Require one selector, ordered dates, distinct groups, and valid tier combinations."""
        if (self.account_id is None) == (self.player_name is None):
            raise ValueError("provide exactly one of account_id or player_name")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if not self.tournament_tiers or len(set(self.tournament_tiers)) != len(
            self.tournament_tiers
        ):
            raise ValueError("tournament_tiers must be non-empty and distinct")
        if TournamentTier.ALL in self.tournament_tiers and len(self.tournament_tiers) != 1:
            raise ValueError("all is mutually exclusive with named tournament tiers")
        if len(set(self.include)) != len(self.include):
            raise ValueError("include values must be distinct")
        return self


class ProfessionalPlayerReference(SparseModel):
    """Stable professional player identity and optional current-team context."""

    account_id: int = Field(gt=0)
    pro_name: str = Field(min_length=1)
    team_id: int | None = Field(default=None, gt=0, exclude_if=omit_none)
    team_name: str | None = Field(default=None, exclude_if=omit_none)


class ProfessionalPlayerCandidate(ProfessionalPlayerReference):
    """Bounded player identity candidate."""


class FantasyAppliedFilters(SparseModel):
    """Effective professional fantasy filters."""

    patch: str
    start_date: date | None = Field(default=None, exclude_if=omit_none)
    end_date: date | None = Field(default=None, exclude_if=omit_none)
    tournament_tiers: list[str]


class FantasyCoverage(SparseModel):
    """Fixed-budget player-history collection accounting."""

    history_records_examined: int = Field(ge=0, le=500)
    details_requested: int = Field(ge=0, le=200)
    details_usable: int = Field(ge=0, le=200)
    history_exhausted: bool
    truncated: bool
    terminal_reason: Literal[
        "requested_count_met", "history_exhausted", "history_record_limit", "hydrated_detail_limit"
    ]

    @model_validator(mode="after")
    def validate_terminal_state(self) -> FantasyCoverage:
        """Keep coverage reason and truncation flags consistent."""
        limited = self.terminal_reason in {"history_record_limit", "hydrated_detail_limit"}
        if limited != self.truncated:
            raise ValueError("only safety-limit terminal reasons are truncated")
        return self


class FantasyEntityReference(SparseModel):
    """Nullable stable ID/name pair for a match entity."""

    team_id: int | None = Field(default=None, gt=0)
    name: str | None = None


class FantasyHeroReference(SparseModel):
    """Nullable hero ID/name pair."""

    hero_id: int | None = Field(default=None, gt=0)
    name: str | None = None


class FantasyMatchContext(SparseModel):
    """Compact player-relative professional-map context."""

    match_id: int = Field(gt=0)
    start_time: datetime
    patch: str | None = None
    tournament_name: str | None = None
    tournament_tier: str | None = None
    series_id: int | None = Field(default=None, gt=0)
    player: ProfessionalPlayerReference
    team: FantasyEntityReference
    opponent: FantasyEntityReference
    hero: FantasyHeroReference
    result: Literal["win", "loss"] | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    team_kills: int | None = Field(default=None, ge=0)
    opponent_kills: int | None = Field(default=None, ge=0)

    @field_serializer("start_time")
    def serialize_start_time(self, value: datetime) -> str:
        """Serialize match time as canonical UTC."""
        return utc_iso(value)


class FantasyRawStats(SparseModel):
    """All nullable TI 2026 raw fantasy inputs with explicit zero semantics."""

    kills: int | None = Field(ge=0)
    deaths: int | None = Field(ge=0)
    assists: int | None = Field(ge=0)
    last_hits: int | None = Field(ge=0)
    denies: int | None = Field(ge=0)
    gold_per_minute: int | None = Field(ge=0)
    madstones_collected: int | None = Field(ge=0)
    tower_last_hits: int | None = Field(ge=0)
    observer_wards_placed: int | None = Field(ge=0)
    camps_stacked: int | None = Field(ge=0)
    runes_picked_up_or_bottled: int | None = Field(ge=0)
    watchers_captured: int | None = Field(ge=0)
    lotuses_taken: int | None = Field(ge=0)
    smoke_of_deceit_uses: int | None = Field(ge=0)
    roshan_last_hits: int | None = Field(ge=0)
    teamfight_participation: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    stun_duration_seconds: float | None = Field(ge=0, allow_inf_nan=False)
    tormentor_last_hits: int | None = Field(ge=0)
    courier_last_hits: int | None = Field(ge=0)
    first_blood: bool | None


class RawEmblemScore(SparseModel):
    """One canonical pre-modifier fantasy score."""

    key: str
    color: Literal["red", "blue", "green"]
    inputs: dict[str, int | float | bool | None]
    raw_points: int | float | None = Field(allow_inf_nan=False)


class FantasyScoring(SparseModel):
    """Canonical ordered pre-modifier emblem scores."""

    emblems: list[RawEmblemScore] = Field(min_length=18, max_length=18)


class FantasyMatchEvidence(SparseModel):
    """One compact eligible professional map."""

    context: FantasyMatchContext
    raw_stats: FantasyRawStats
    fantasy_scoring: FantasyScoring | None = Field(default=None, exclude_if=omit_none)
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)


class PlayerFantasyResponse(SparseModel):
    """Successful evidence, selection candidates, or one structured error."""

    player: ProfessionalPlayerReference | None = Field(default=None, exclude_if=omit_none)
    candidates: list[ProfessionalPlayerCandidate] | None = Field(
        default=None, exclude_if=omit_none_or_empty
    )
    filters: FantasyAppliedFilters | None = Field(default=None, exclude_if=omit_none)
    coverage: FantasyCoverage | None = Field(default=None, exclude_if=omit_none)
    returned_count: int | None = Field(default=None, ge=0, le=100, exclude_if=omit_none)
    reference_uri: str | None = Field(default=None, exclude_if=omit_none)
    matches: list[FantasyMatchEvidence] = Field(default_factory=list)
    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)
    error: ToolErrorDetail | None = Field(default=None, exclude_if=omit_none)


JsonObject = dict[str, Any]
