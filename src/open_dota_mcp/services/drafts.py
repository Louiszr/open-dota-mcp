"""Professional draft retrieval and compact domain transformation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.errors import DataWarning, ErrorStatus, ToolErrorDetail, UpstreamError
from open_dota_mcp.models.common import (
    HeroIdentity,
    PlayerIdentity,
    Side,
    TeamIdentity,
    utc_datetime,
)
from open_dota_mcp.models.drafts import (
    ActionType,
    Competition,
    Completeness,
    DraftAction,
    DraftOutcome,
    DraftResponse,
    DraftTiming,
    MatchDraft,
    MatchResult,
    OrderingQuality,
    Provenance,
)

INCLUDE_GROUPS = frozenset({"competition", "result", "draft_timing", "provenance"})


class DraftService:
    """Retrieve, verify, enrich, and transform professional match drafts."""

    def __init__(
        self,
        client: OpenDotaClient,
        *,
        now: Callable[[], datetime] | None = None,
        concurrency: int = 5,
    ) -> None:
        """Initialize the service with bounded retrieval concurrency."""
        self.client = client
        self._now = now or (lambda: datetime.now(UTC))
        self._semaphore = asyncio.Semaphore(concurrency)

    async def get_drafts(
        self, match_ids: list[int], *, include: list[str] | None = None
    ) -> DraftResponse:
        """Return first-occurrence ordered outcomes for one to ten match IDs.

        Args:
            match_ids: Valid positive match identifiers.
            include: Additive response groups.

        Returns:
            Ordered batch response with sparse per-match failures.

        Raises:
            ValueError: If IDs or include groups violate the public contract.
        """
        ids = validate_match_ids(match_ids)
        groups = validate_include(include)
        references = await self._references()
        outcomes = await asyncio.gather(
            *(self._get_one(match_id, groups, references) for match_id in ids)
        )
        return DraftResponse(requested_match_ids=ids, matches=list(outcomes))

    async def _get_one(
        self,
        match_id: int,
        include: set[str],
        references: tuple[dict[int, str], dict[int, str], dict[int, str], list[DataWarning]],
    ) -> DraftOutcome:
        async with self._semaphore:
            try:
                raw = await self.client.get_match(match_id)
                league_id = _integer(raw.get("leagueid"))
                if league_id is None or not await self._is_professional(match_id, league_id):
                    return _failed(
                        match_id,
                        ErrorStatus.NOT_PROFESSIONAL,
                        "not_professional",
                        "Match is not on the selected professional league surface",
                    )
                if not isinstance(raw.get("picks_bans"), list) or not raw["picks_bans"]:
                    return _failed(
                        match_id,
                        ErrorStatus.NOT_PARSED,
                        "not_parsed",
                        "Parsed draft actions are not available",
                    )
                heroes, patches, professionals, reference_warnings = references
                draft = map_match_draft(
                    raw,
                    heroes=heroes,
                    patches=patches,
                    professionals=professionals,
                    include=include,
                    retrieved_at=self._now(),
                    reference_warnings=reference_warnings,
                )
                return DraftOutcome(match_id=match_id, draft=draft)
            except asyncio.CancelledError:
                raise
            except UpstreamError as exc:
                status = (
                    ErrorStatus.UNAVAILABLE
                    if exc.status_code == 404
                    else ErrorStatus.UPSTREAM_ERROR
                )
                return DraftOutcome(
                    match_id=match_id,
                    error=exc.detail("get_pro_match_drafts", target=str(match_id), status=status),
                )

    async def _is_professional(self, match_id: int, league_id: int) -> bool:
        matches = await self.client.get_league_matches(league_id)
        return any(_integer(item.get("match_id")) == match_id for item in matches)

    async def _references(
        self,
    ) -> tuple[dict[int, str], dict[int, str], dict[int, str], list[DataWarning]]:
        calls = [self.client.get_heroes(), self.client.get_patches(), self.client.get_pro_players()]
        results = await asyncio.gather(*calls, return_exceptions=True)
        warnings: list[DataWarning] = []
        normalized: list[list[dict[str, Any]]] = []
        for label, result in zip(("hero", "patch", "player"), results, strict=True):
            if isinstance(result, BaseException):
                normalized.append([])
                warnings.append(
                    DataWarning(
                        code="reference_enrichment_failed",
                        message=f"{label.capitalize()} reference enrichment was unavailable",
                    )
                )
            else:
                normalized.append(result)
        heroes = {
            int(item["id"]): str(item["localized_name"])
            for item in normalized[0]
            if _integer(item.get("id")) is not None and item.get("localized_name")
        }
        patches = {
            identifier: str(item.get("name") or item.get("patch_name"))
            for item in normalized[1]
            if (identifier := _integer(item.get("id") or item.get("patch"))) is not None
            and (item.get("name") or item.get("patch_name"))
        }
        professionals = {
            int(item["account_id"]): str(item["name"])
            for item in normalized[2]
            if _integer(item.get("account_id")) is not None and item.get("name")
        }
        return heroes, patches, professionals, warnings


def validate_match_ids(match_ids: list[int]) -> list[int]:
    """Validate and silently de-duplicate draft IDs at first occurrence."""
    if not 1 <= len(match_ids) <= 10 or any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in match_ids
    ):
        raise ValueError("match_ids must contain 1 to 10 positive integers")
    return list(dict.fromkeys(match_ids))


def validate_include(include: list[str] | None) -> set[str]:
    """Validate additive draft field groups."""
    groups = set(include or [])
    if invalid := groups - INCLUDE_GROUPS:
        raise ValueError(f"Unsupported include group: {', '.join(sorted(invalid))}")
    return groups


def map_match_draft(
    raw: dict[str, Any],
    *,
    heroes: dict[int, str],
    patches: dict[int, str],
    professionals: dict[int, str],
    include: set[str],
    retrieved_at: datetime,
    reference_warnings: list[DataWarning] | None = None,
) -> MatchDraft:
    """Transform one eligible OpenDota record into the published draft model."""
    match_id = int(raw["match_id"])
    radiant = TeamIdentity(
        team_id=_integer(raw.get("radiant_team_id")), name=raw.get("radiant_name")
    )
    dire = TeamIdentity(team_id=_integer(raw.get("dire_team_id")), name=raw.get("dire_name"))
    raw_actions = [item for item in raw.get("picks_bans", []) if isinstance(item, dict)]
    orders = [item.get("order") for item in raw_actions]
    authoritative = all(
        isinstance(order, int) and not isinstance(order, bool) for order in orders
    ) and sorted(orders) == list(range(len(raw_actions)))
    indexed = list(enumerate(raw_actions))
    if authoritative:
        indexed.sort(key=lambda pair: int(pair[1]["order"]))
    timings = raw.get("draft_timings") if isinstance(raw.get("draft_timings"), list) else []
    actions = [
        _map_action(
            item,
            source_index=source_index,
            radiant=radiant,
            dire=dire,
            heroes=heroes,
            professionals=professionals,
            players=[item for item in raw.get("players", []) if isinstance(item, dict)],
            timings=[item for item in timings if isinstance(item, dict)],
            include_timing="draft_timing" in include,
        )
        for source_index, item in indexed
    ]
    warnings = list(reference_warnings or [])
    if not authoritative:
        warnings.append(
            DataWarning(
                code="degraded_draft_order",
                message=(
                    "Draft order values were incomplete or inconsistent; upstream sequence retained"
                ),
                path="draft_actions",
            )
        )
    patch_id = _integer(raw.get("patch"))
    if patch_id is not None and patch_id not in patches:
        warnings.append(
            DataWarning(
                code="missing_patch_version",
                message="Patch label is unavailable",
                path="patch_version",
            )
        )
    start_time = utc_datetime(raw.get("start_time"))
    all_warnings = warnings + [warning for action in actions for warning in action.warnings or []]
    draft = MatchDraft(
        match_id=match_id,
        start_time=start_time,
        match_date=start_time.date() if start_time else None,
        patch_id=patch_id,
        patch_version=patches.get(patch_id) if patch_id is not None else None,
        radiant_team=radiant,
        dire_team=dire,
        ordering_quality=OrderingQuality.AUTHORITATIVE
        if authoritative
        else OrderingQuality.DEGRADED,
        completeness=Completeness.PARTIAL if all_warnings else Completeness.COMPLETE,
        draft_actions=actions,
        warnings=warnings or None,
    )
    if "competition" in include:
        league = raw.get("league") if isinstance(raw.get("league"), dict) else {}
        draft.competition = Competition(
            league_id=_integer(raw.get("leagueid")),
            league_name=league.get("name") or raw.get("league_name"),
            series_id=_integer(raw.get("series_id")),
            series_type=_integer(raw.get("series_type")),
        )
    if "result" in include:
        radiant_win = raw.get("radiant_win")
        draft.result = MatchResult(
            winner=("radiant" if radiant_win else "dire")
            if isinstance(radiant_win, bool)
            else None,
            radiant_score=_integer(raw.get("radiant_score")),
            dire_score=_integer(raw.get("dire_score")),
            duration_seconds=_integer(raw.get("duration")),
        )
    if "provenance" in include:
        draft.provenance = Provenance(
            retrieved_at=retrieved_at,
            parse_version=_integer(raw.get("version")),
            upstream_match_version=_integer(raw.get("match_seq_num")),
            warnings=reference_warnings or None,
        )
    return draft


def _map_action(
    raw: dict[str, Any],
    *,
    source_index: int,
    radiant: TeamIdentity,
    dire: TeamIdentity,
    heroes: dict[int, str],
    professionals: dict[int, str],
    players: list[dict[str, Any]],
    timings: list[dict[str, Any]],
    include_timing: bool,
) -> DraftAction:
    warnings: list[DataWarning] = []
    hero_id = _integer(raw.get("hero_id")) or 0
    side = Side.RADIANT if raw.get("team") == 0 else Side.DIRE if raw.get("team") == 1 else None
    if hero_id not in heroes:
        warnings.append(
            DataWarning(
                code="missing_hero_name",
                message="Hero label is unavailable",
                path="hero.localized_name",
            )
        )
    is_pick = raw.get("is_pick") is True
    player = _player_for_pick(hero_id, side, players, professionals, warnings) if is_pick else None
    action = DraftAction(
        source_index=source_index,
        order=_integer(raw.get("order")),
        action_type=ActionType.PICK if is_pick else ActionType.BAN,
        acting_side=side,
        acting_team=radiant
        if side == Side.RADIANT
        else dire
        if side == Side.DIRE
        else TeamIdentity(),
        hero=HeroIdentity(hero_id=hero_id, localized_name=heroes.get(hero_id)),
        player=player,
        warnings=warnings or None,
    )
    if include_timing:
        matches = [item for item in timings if item.get("order") == raw.get("order")]
        if len(matches) == 1:
            action.timing = DraftTiming(
                extra_time_seconds=_integer(matches[0].get("extra_time")),
                total_time_taken_seconds=_integer(matches[0].get("total_time_taken")),
            )
        else:
            action.timing = DraftTiming()
            action.warnings = (action.warnings or []) + [
                DataWarning(
                    code="unavailable_draft_timing",
                    message="Draft timing could not be associated uniquely",
                    path="timing",
                )
            ]
    return action


def _player_for_pick(
    hero_id: int,
    side: Side | None,
    players: list[dict[str, Any]],
    professionals: dict[int, str],
    warnings: list[DataWarning],
) -> PlayerIdentity:
    candidates = [
        player
        for player in players
        if _integer(player.get("hero_id")) == hero_id and _player_side(player) == side
    ]
    if len(candidates) != 1:
        code = "ambiguous_player_mapping" if len(candidates) > 1 else "unavailable_player_mapping"
        source = "ambiguous" if len(candidates) > 1 else "unavailable"
        warnings.append(
            DataWarning(
                code=code, message="Picked hero could not be mapped uniquely", path="player"
            )
        )
        return PlayerIdentity(identity_source=source)
    candidate = candidates[0]
    account_id = _integer(candidate.get("account_id"))
    professional_name = candidate.get("name") or professionals.get(account_id or -1)
    if professional_name:
        return PlayerIdentity(
            account_id=account_id,
            professional_name=str(professional_name),
            display_identity=str(professional_name),
            identity_source="professional_name",
        )
    if account_id is not None:
        warnings.append(
            DataWarning(
                code="missing_professional_name",
                message="Professional name is unavailable; Steam32 fallback used",
                path="player.professional_name",
            )
        )
        return PlayerIdentity(
            account_id=account_id,
            display_identity=account_id,
            identity_source="steam32_fallback",
        )
    warnings.append(
        DataWarning(
            code="missing_player_account",
            message="Player account is unavailable",
            path="player.account_id",
        )
    )
    return PlayerIdentity(identity_source="unavailable")


def _player_side(player: dict[str, Any]) -> Side | None:
    if isinstance(player.get("isRadiant"), bool):
        return Side.RADIANT if player["isRadiant"] else Side.DIRE
    slot = _integer(player.get("player_slot"))
    return (
        Side.RADIANT if slot is not None and slot < 128 else Side.DIRE if slot is not None else None
    )


def _failed(match_id: int, status: ErrorStatus, code: str, message: str) -> DraftOutcome:
    return DraftOutcome(
        match_id=match_id,
        error=ToolErrorDetail(
            status=status,
            code=code,
            message=message,
            tool="get_pro_match_drafts",
            target=str(match_id),
        ),
    )


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
