"""Shared stable domain value objects."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, field_serializer

from open_dota_mcp.errors import DataWarning, SparseModel, omit_none_or_empty


class Side(StrEnum):
    """Dota map side."""

    RADIANT = "radiant"
    DIRE = "dire"


class Winner(StrEnum):
    """Winning map side."""

    RADIANT = "radiant"
    DIRE = "dire"


class TeamResult(StrEnum):
    """Result relative to a selected team."""

    WIN = "win"
    LOSS = "loss"


class TeamIdentity(SparseModel):
    """Stable team identity with nullable upstream labels."""

    team_id: int | None = Field(default=None, gt=0)
    name: str | None = None
    tag: str | None = None


class LeagueIdentity(SparseModel):
    """Stable OpenDota league identity."""

    league_id: int = Field(gt=0)
    name: str | None = None
    tier: str | None = None


class HeroIdentity(SparseModel):
    """Stable hero identity and optional localized label."""

    hero_id: int = Field(gt=0)
    localized_name: str | None = None


class PlayerIdentity(SparseModel):
    """Professional identity with explicit Steam32 fallback semantics."""

    account_id: int | None = Field(default=None, ge=0)
    professional_name: str | None = None
    display_identity: str | int | None = None
    identity_source: str


class PageMetadata(SparseModel):
    """Bounded continuation page metadata."""

    returned_count: int = Field(ge=0)
    page_size: int = Field(ge=1, le=100)
    continuation_token: str | None = None
    terminal: bool
    snapshot_expires_at: datetime | None = None

    @field_serializer("snapshot_expires_at")
    def serialize_expiry(self, value: datetime | None) -> str | None:
        """Serialize expiry timestamps in canonical UTC form."""
        return utc_iso(value) if value is not None else None


class WarningCollection(SparseModel):
    """Reusable optional warning collection."""

    warnings: list[DataWarning] | None = Field(default=None, exclude_if=omit_none_or_empty)


def utc_datetime(timestamp: int | float | None) -> datetime | None:
    """Convert a Unix timestamp to an aware UTC datetime.

    Args:
        timestamp: Unix seconds or ``None``.

    Returns:
        An aware UTC datetime, or ``None``.
    """
    return datetime.fromtimestamp(timestamp, tz=UTC) if timestamp is not None else None


def utc_iso(value: datetime) -> str:
    """Serialize a datetime as an ISO 8601 UTC string ending in ``Z``.

    Args:
        value: Aware or naive datetime; naive values are interpreted as UTC.

    Returns:
        Canonical UTC timestamp.
    """
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")
