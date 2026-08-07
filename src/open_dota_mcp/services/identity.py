"""Deterministic league and team identity resolution."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from open_dota_mcp.clients.opendota import OpenDotaClient


@dataclass(frozen=True, slots=True)
class Resolution[T: dict[str, Any]]:
    """A unique identity, bounded candidates, or a no-match result."""

    selected: T | None
    candidates: list[T]
    query: str


def normalize_identity(value: str) -> str:
    """Normalize Unicode case, punctuation, and spacing for identity comparison.

    Args:
        value: Upstream or caller-provided name/tag.

    Returns:
        A stable comparison string.
    """
    folded = unicodedata.normalize("NFKD", value).casefold()
    letters = "".join(character for character in folded if not unicodedata.combining(character))
    return re.sub(r"[^\w]+", " ", letters, flags=re.UNICODE).strip()


def normalize_player_name(value: str) -> str:
    """Normalize a professional name using the fantasy identity contract.

    Args:
        value: Caller query or professional catalog name.

    Returns:
        NFKC/casefolded text with punctuation and whitespace runs collapsed.
    """
    folded = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]+", " ", folded, flags=re.UNICODE).strip()


def resolve_professional_player(
    query: str, professionals: list[dict[str, Any]]
) -> Resolution[dict[str, Any]]:
    """Resolve only a unique exact professional-name match.

    Args:
        query: Professional display-name selector.
        professionals: OpenDota ``/proPlayers`` catalog.

    Returns:
        Unique selection or at most ten deterministic exact/substring candidates.
    """
    normalized = normalize_player_name(query)
    if not normalized:
        return Resolution(None, [], normalized)
    records = [
        item
        for item in professionals
        if _positive_integer(item.get("account_id"))
        and normalize_player_name(str(item.get("name") or ""))
    ]
    exact = [
        item for item in records if normalize_player_name(str(item.get("name") or "")) == normalized
    ]
    if len(exact) == 1:
        return Resolution(exact[0], [], normalized)
    candidates = exact or [
        item for item in records if normalized in normalize_player_name(str(item.get("name") or ""))
    ]
    ranked = sorted(
        candidates,
        key=lambda item: (
            normalize_player_name(str(item.get("name") or "")),
            int(item["account_id"]),
        ),
    )[:10]
    return Resolution(None, ranked, normalized)


def professional_by_account_id(
    account_id: int, professionals: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the exact positive professional account record when present."""
    return next(
        (item for item in professionals if _positive_integer(item.get("account_id")) == account_id),
        None,
    )


def resolve_league(query: str, leagues: list[dict[str, Any]]) -> Resolution[dict[str, Any]]:
    """Resolve a league by normalized exact name or ranked substring.

    Args:
        query: Nonblank league query.
        leagues: OpenDota league catalog.

    Returns:
        Resolution containing at most ten deterministic candidates.
    """
    normalized = normalize_identity(query)
    if not normalized:
        return Resolution(None, [], normalized)
    records = [item for item in leagues if normalize_identity(str(item.get("name") or ""))]
    exact = [
        item for item in records if normalize_identity(str(item.get("name") or "")) == normalized
    ]
    if len(exact) == 1:
        return Resolution(exact[0], [], normalized)
    matches = [
        item for item in records if normalized in normalize_identity(str(item.get("name") or ""))
    ]
    ranked = sorted(matches, key=lambda item: _league_rank(item, normalized))[:10]
    return Resolution(None, ranked, normalized)


def resolve_team(query: str, teams: list[dict[str, Any]]) -> Resolution[dict[str, Any]]:
    """Resolve a team by exact normalized name/tag or bounded substring candidates.

    Args:
        query: Nonblank team name or tag.
        teams: Complete traversed team catalog.

    Returns:
        Resolution containing a unique identity or at most ten candidates.
    """
    normalized = normalize_identity(query)
    if not normalized:
        return Resolution(None, [], normalized)

    def keys(item: dict[str, Any]) -> set[str]:
        """Return normalized team name and tag comparison keys."""
        return {
            normalize_identity(str(item.get("name") or "")),
            normalize_identity(str(item.get("tag") or "")),
        }

    exact = [item for item in teams if normalized in keys(item)]
    if len(exact) == 1:
        return Resolution(exact[0], [], normalized)
    matches = [item for item in teams if any(normalized in key for key in keys(item) if key)]
    ranked = sorted(matches, key=lambda item: _team_rank(item, normalized))[:10]
    return Resolution(None, ranked, normalized)


async def load_team_catalog(client: OpenDotaClient) -> list[dict[str, Any]]:
    """Traverse the OpenDota team catalog until an empty page.

    Args:
        client: Typed OpenDota client.

    Returns:
        Every unique team record in upstream page order.

    Raises:
        ValueError: If the upstream repeats a non-empty catalog page.
    """
    result: list[dict[str, Any]] = []
    seen_pages: set[str] = set()
    page = 0
    while True:
        records = await client.get_teams_page(page)
        if not records:
            return result
        fingerprint = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
        if fingerprint in seen_pages:
            raise ValueError("OpenDota repeated a team catalog page")
        seen_pages.add(fingerprint)
        result.extend(records)
        page += 1


def _league_rank(item: dict[str, Any], normalized: str) -> tuple[int, int, str, int]:
    name = normalize_identity(str(item.get("name") or ""))
    return (
        0 if name.startswith(normalized) else 1,
        len(name),
        name,
        int(item.get("leagueid") or 0),
    )


def _team_rank(item: dict[str, Any], normalized: str) -> tuple[int, int, float, str, int]:
    name = normalize_identity(str(item.get("name") or ""))
    tag = normalize_identity(str(item.get("tag") or ""))
    return (
        0
        if tag == normalized
        else 1
        if name.startswith(normalized) or tag.startswith(normalized)
        else 2,
        min((len(key) for key in (name, tag) if key), default=10_000),
        -float(item.get("last_match_time") or 0),
        name,
        int(item.get("team_id") or 0),
    )


def _positive_integer(value: object) -> int | None:
    """Return a strict positive integer without accepting booleans."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
