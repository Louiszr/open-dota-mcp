"""Bounded professional player fantasy evidence collection and mapping."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import Any

import regex
from pydantic import ValidationError

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.errors import DataWarning, ToolErrorDetail, UpstreamError
from open_dota_mcp.fantasy_rules import score_raw_stats
from open_dota_mcp.models.fantasy import (
    FantasyAppliedFilters,
    FantasyCoverage,
    FantasyEntityReference,
    FantasyHeroReference,
    FantasyInclude,
    FantasyMatchContext,
    FantasyMatchEvidence,
    FantasyRawStats,
    FantasyScoring,
    PlayerFantasyRequest,
    PlayerFantasyResponse,
    ProfessionalPlayerCandidate,
    ProfessionalPlayerReference,
)
from open_dota_mcp.services.identity import professional_by_account_id, resolve_professional_player

TOOL_NAME = "get_pro_player_fantasy"
REFERENCE_URI = "opendota://fantasy/ti-2026/scoring"
HISTORY_LIMIT = 500
DETAIL_LIMIT = 200
PAGE_SIZE = 100
CONCURRENCY = 5
TORMENTOR_TYPES = {"CHAT_MESSAGE_MINIBOSS_KILL", "miniboss_kill", "tormentor_kill"}


class FantasyService:
    """Resolve a professional and collect fail-closed fantasy evidence."""

    def __init__(self, client: OpenDotaClient) -> None:
        """Initialize the service with its typed OpenDota client."""
        self.client = client
        self._semaphore = asyncio.Semaphore(CONCURRENCY)

    async def get_fantasy(
        self,
        *,
        account_id: int | None = None,
        player_name: str | None = None,
        match_count: int | None = None,
        version_pattern: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        tournament_tiers: list[str] | None = None,
        include: list[str] | None = None,
    ) -> PlayerFantasyResponse:
        """Return bounded professional map evidence or an actionable structured outcome."""
        try:
            request = PlayerFantasyRequest.model_validate(
                {
                    "account_id": account_id,
                    "player_name": player_name,
                    "match_count": 20 if match_count is None else match_count,
                    "version_pattern": version_pattern,
                    "start_date": start_date,
                    "end_date": end_date,
                    "tournament_tiers": ["premium"]
                    if tournament_tiers is None
                    else tournament_tiers,
                    "include": [] if include is None else include,
                }
            )
            pattern = _compile_pattern(request.version_pattern)
        except (ValidationError, ValueError) as exc:
            return _error(
                "invalid_request", _validation_message(exc), valid_values=_valid_values(exc)
            )

        try:
            professionals = await self.client.get_pro_players()
            identity = _resolve_player(request, professionals)
            if isinstance(identity, PlayerFantasyResponse):
                return identity
            patches, leagues, heroes = await asyncio.gather(
                self.client.get_patches(), self.client.get_leagues(), self.client.get_heroes()
            )
            patch_names, effective_patch, pattern = _patch_filter(patches, request, pattern)
            league_refs = _league_references(leagues)
            hero_refs = _hero_references(heroes)
            return await self._collect(
                request,
                identity,
                professionals,
                patch_names,
                effective_patch,
                pattern,
                league_refs,
                hero_refs,
            )
        except asyncio.CancelledError:
            raise
        except UpstreamError as exc:
            return PlayerFantasyResponse(error=exc.detail(TOOL_NAME))
        except (ValidationError, ValueError) as exc:
            return _error("invalid_request", _validation_message(exc))

    async def _collect(
        self,
        request: PlayerFantasyRequest,
        identity: ProfessionalPlayerReference,
        professionals: list[dict[str, Any]],
        patch_names: dict[int, str],
        effective_patch: str,
        pattern: regex.Pattern[str],
        league_refs: dict[int, tuple[str, str]],
        hero_refs: dict[int, str],
    ) -> PlayerFantasyResponse:
        matches: list[FantasyMatchEvidence] = []
        seen: set[int] = set()
        examined = requested = usable = 0
        offset = 0
        exhausted = False
        partial_failures = 0
        while (
            examined < HISTORY_LIMIT
            and requested < DETAIL_LIMIT
            and len(matches) < request.match_count
        ):
            page_limit = min(PAGE_SIZE, HISTORY_LIMIT - examined)
            history = await self.client.get_player_matches(
                identity.account_id, limit=page_limit, offset=offset
            )
            if not history:
                exhausted = True
                break
            normalized = sorted(
                history,
                key=lambda item: (
                    _number(item.get("start_time")) or 0,
                    _positive_int(item.get("match_id")) or 0,
                ),
                reverse=True,
            )
            offset += len(history)
            for start in range(0, len(normalized), CONCURRENCY):
                if (
                    len(matches) >= request.match_count
                    or examined >= HISTORY_LIMIT
                    or requested >= DETAIL_LIMIT
                ):
                    break
                chunk: list[tuple[dict[str, Any], int]] = []
                for summary in normalized[start : start + CONCURRENCY]:
                    if examined >= HISTORY_LIMIT:
                        break
                    examined += 1
                    match_id = _positive_int(summary.get("match_id"))
                    if (
                        match_id is None
                        or match_id in seen
                        or not _summary_date_possible(summary, request)
                    ):
                        continue
                    seen.add(match_id)
                    if requested >= DETAIL_LIMIT:
                        break
                    requested += 1
                    chunk.append((summary, match_id))
                details = await asyncio.gather(
                    *(self._get_detail(match_id) for _, match_id in chunk), return_exceptions=True
                )
                for (summary, _match_id), detail in zip(chunk, details, strict=True):
                    if isinstance(detail, BaseException):
                        if isinstance(detail, asyncio.CancelledError):
                            raise detail
                        partial_failures += 1
                        continue
                    evidence = map_fantasy_match(
                        detail,
                        summary=summary,
                        player=identity,
                        patch_names=patch_names,
                        league_refs=league_refs,
                        hero_refs=hero_refs,
                        pattern=pattern,
                        request=request,
                        include_scoring=FantasyInclude.FANTASY_SCORING in request.include,
                    )
                    if evidence is not None:
                        usable += 1
                        matches.append(evidence)
                        if len(matches) >= request.match_count:
                            break
            if len(history) < page_limit:
                exhausted = True
                break
        matches.sort(
            key=lambda item: (item.context.start_time, item.context.match_id), reverse=True
        )
        matches = matches[: request.match_count]
        if len(matches) >= request.match_count:
            reason, truncated = "requested_count_met", False
        elif requested >= DETAIL_LIMIT:
            reason, truncated = "hydrated_detail_limit", True
        elif examined >= HISTORY_LIMIT:
            reason, truncated = "history_record_limit", True
        else:
            reason, truncated, exhausted = "history_exhausted", False, True
        warnings = _root_warnings(bool(matches), partial_failures, reason if truncated else None)
        return PlayerFantasyResponse(
            player=identity,
            filters=FantasyAppliedFilters(
                patch=effective_patch,
                start_date=request.start_date,
                end_date=request.end_date,
                tournament_tiers=[str(value) for value in request.tournament_tiers],
            ),
            coverage=FantasyCoverage(
                history_records_examined=examined,
                details_requested=requested,
                details_usable=usable,
                history_exhausted=exhausted,
                truncated=truncated,
                terminal_reason=reason,
            ),
            returned_count=len(matches),
            reference_uri=REFERENCE_URI
            if FantasyInclude.FANTASY_SCORING in request.include
            else None,
            matches=matches,
            warnings=warnings,
        )

    async def _get_detail(self, match_id: int) -> dict[str, Any]:
        """Hydrate one detail under the fixed concurrency boundary."""
        async with self._semaphore:
            return await self.client.get_match(match_id)


def map_fantasy_match(
    raw: dict[str, Any],
    *,
    summary: dict[str, Any],
    player: ProfessionalPlayerReference,
    patch_names: dict[int, str],
    league_refs: dict[int, tuple[str, str]],
    hero_refs: dict[int, str],
    pattern: regex.Pattern[str],
    request: PlayerFantasyRequest,
    include_scoring: bool,
) -> FantasyMatchEvidence | None:
    """Map one detail after mandatory professional provenance and caller filters."""
    match_id = _positive_int(raw.get("match_id"))
    version = _positive_int(raw.get("version"))
    start_timestamp = _number(raw.get("start_time"))
    league_id = _positive_int(raw.get("leagueid"))
    summary_league = _positive_int(summary.get("leagueid"))
    if (
        match_id is None
        or version is None
        or start_timestamp is None
        or not isinstance(raw.get("radiant_win"), bool)
        or league_id not in league_refs
        or (summary_league is not None and summary_league != league_id)
    ):
        return None
    rows = (
        [item for item in raw.get("players", []) if isinstance(item, dict)]
        if isinstance(raw.get("players"), list)
        else []
    )
    selected = [item for item in rows if _positive_int(item.get("account_id")) == player.account_id]
    if len(selected) != 1:
        return None
    row = selected[0]
    patch = patch_names.get(_positive_int(raw.get("patch")) or -1)
    started = datetime.fromtimestamp(start_timestamp, UTC)
    league_name, league_tier = league_refs[league_id]
    nested_league = raw.get("league") if isinstance(raw.get("league"), dict) else {}
    nested_tier = str(nested_league.get("tier") or "")
    if nested_tier and nested_tier != league_tier:
        return None
    if patch is None or _safe_fullmatch(pattern, patch) is False:
        return None
    if request.start_date and started.date() < request.start_date:
        return None
    if request.end_date and started.date() > request.end_date:
        return None
    tiers = {str(value) for value in request.tournament_tiers}
    if "all" not in tiers and league_tier not in tiers:
        return None
    side_radiant = _is_radiant(row)
    if side_radiant is None:
        return None
    team_id = _positive_int(raw.get("radiant_team_id" if side_radiant else "dire_team_id"))
    opponent_id = _positive_int(raw.get("dire_team_id" if side_radiant else "radiant_team_id"))
    team_name = _optional_string(raw.get("radiant_name" if side_radiant else "dire_name"))
    opponent_name = _optional_string(raw.get("dire_name" if side_radiant else "radiant_name"))
    radiant_score = _nonnegative_int(raw.get("radiant_score"))
    dire_score = _nonnegative_int(raw.get("dire_score"))
    team_kills = radiant_score if side_radiant else dire_score
    opponent_kills = dire_score if side_radiant else radiant_score
    stats, warnings = map_raw_stats(raw, row, rows, side_radiant, team_kills, patch)
    context = FantasyMatchContext(
        match_id=match_id,
        start_time=started,
        patch=patch,
        tournament_name=_optional_string(nested_league.get("name"))
        or _optional_string(summary.get("league_name"))
        or league_name,
        tournament_tier=league_tier,
        series_id=_positive_int(raw.get("series_id")),
        player=player,
        team=FantasyEntityReference(team_id=team_id, name=team_name),
        opponent=FantasyEntityReference(team_id=opponent_id, name=opponent_name),
        hero=FantasyHeroReference(
            hero_id=_positive_int(row.get("hero_id")),
            name=hero_refs.get(_positive_int(row.get("hero_id")) or -1),
        ),
        result="win" if bool(raw["radiant_win"]) == side_radiant else "loss",
        duration_seconds=_nonnegative_int(raw.get("duration")),
        team_kills=team_kills,
        opponent_kills=opponent_kills,
    )
    scoring = FantasyScoring(emblems=score_raw_stats(stats)) if include_scoring else None
    return FantasyMatchEvidence(
        context=context, raw_stats=stats, fantasy_scoring=scoring, warnings=warnings
    )


def map_raw_stats(
    match: dict[str, Any],
    row: dict[str, Any],
    players: list[dict[str, Any]],
    radiant: bool,
    team_kills: int | None,
    patch: str,
) -> tuple[FantasyRawStats, list[DataWarning]]:
    """Map compatible raw values while preserving null, zero, and false."""
    kills = _nonnegative_int(row.get("kills"))
    assists = _nonnegative_int(row.get("assists"))
    warnings: list[DataWarning] = []
    participation = None
    if team_kills == 0:
        warnings.append(
            DataWarning(
                code="team_kills_zero",
                message=(
                    "Teamfight participation is unavailable because the player's team recorded "
                    "zero kills."
                ),
            )
        )
    elif team_kills is not None and team_kills > 0 and kills is not None and assists is not None:
        participation = min(1.0, (kills + assists) / team_kills)
    item_uses = row.get("item_uses") if isinstance(row.get("item_uses"), dict) else {}
    first_blood = _first_blood(row, players)
    stats = FantasyRawStats(
        kills=kills,
        deaths=_nonnegative_int(row.get("deaths")),
        assists=assists,
        last_hits=_nonnegative_int(row.get("last_hits")),
        denies=_nonnegative_int(row.get("denies")),
        gold_per_minute=_first_known_integer(row.get("gold_per_min"), row.get("gold_per_minute")),
        madstones_collected=None,
        tower_last_hits=_nonnegative_int(row.get("tower_kills")),
        observer_wards_placed=_nonnegative_int(row.get("obs_placed")),
        camps_stacked=_nonnegative_int(row.get("camps_stacked")),
        runes_picked_up_or_bottled=_nonnegative_int(row.get("rune_pickups")),
        watchers_captured=None,
        lotuses_taken=None,
        smoke_of_deceit_uses=_nonnegative_int(item_uses.get("smoke_of_deceit")),
        roshan_last_hits=_first_known_integer(row.get("roshans_killed"), row.get("roshan_kills")),
        teamfight_participation=participation,
        stun_duration_seconds=_nonnegative_number(row.get("stuns")),
        tormentor_last_hits=_tormentor_credit(match, row, radiant, patch),
        courier_last_hits=_first_known_integer(
            row.get("couriers_killed"), row.get("courier_kills")
        ),
        first_blood=first_blood,
    )
    return stats, warnings


def _tormentor_credit(
    match: dict[str, Any], row: dict[str, Any], radiant: bool, patch: str
) -> int | None:
    if _patch_tuple(patch) < (7, 33):
        return None
    objectives = match.get("objectives")
    if not isinstance(objectives, list):
        return None
    events = [
        item
        for item in objectives
        if isinstance(item, dict) and item.get("type") in TORMENTOR_TYPES
    ]
    selected_slot = _nonnegative_int(row.get("player_slot"))
    count = 0
    for event in events:
        slot = _nonnegative_int(event.get("player_slot"))
        team = _nonnegative_int(event.get("team"))
        event_radiant = team in {0, 2} if team is not None else None
        if slot is None or event_radiant is None:
            return None
        matching = [
            item
            for item in match.get("players", [])
            if isinstance(item, dict) and _nonnegative_int(item.get("player_slot")) == slot
        ]
        if len(matching) != 1 or _is_radiant(matching[0]) != event_radiant:
            return None
        if slot == selected_slot and event_radiant == radiant:
            count += 1
    return count


def _first_blood(row: dict[str, Any], players: list[dict[str, Any]]) -> bool | None:
    value = _binary_flag(row.get("firstblood_claimed"))
    if value is True:
        return True
    claims = [_binary_flag(item.get("firstblood_claimed")) for item in players]
    if any(item is True for item in claims):
        return False
    return None


def _binary_flag(value: Any) -> bool | None:
    """Decode OpenDota's nullable boolean-compatible integer flags."""
    if isinstance(value, bool):
        return value
    if type(value) is int and value in {0, 1}:
        return bool(value)
    return None


def _resolve_player(
    request: PlayerFantasyRequest, professionals: list[dict[str, Any]]
) -> ProfessionalPlayerReference | PlayerFantasyResponse:
    record = (
        professional_by_account_id(request.account_id, professionals)
        if request.account_id
        else None
    )
    if request.account_id is not None and record is None:
        return _error(
            "identity_not_found", "The account ID is not present in the professional player catalog"
        )
    if request.player_name is not None:
        resolution = resolve_professional_player(request.player_name, professionals)
        if not resolution.query:
            return _error("invalid_player_name", "player_name must contain letters or digits")
        if resolution.selected is None:
            if not resolution.candidates:
                return _error("identity_not_found", "No professional player matched that name")
            return PlayerFantasyResponse(
                candidates=[_player_candidate(item) for item in resolution.candidates]
            )
        record = resolution.selected
    assert record is not None
    return _player_reference(record)


def _player_reference(record: dict[str, Any]) -> ProfessionalPlayerReference:
    account_id = _positive_int(record.get("account_id"))
    name = _optional_string(record.get("name"))
    if account_id is None or name is None:
        raise ValueError("professional player record is missing identity fields")
    return ProfessionalPlayerReference(
        account_id=account_id,
        pro_name=name,
        team_id=_positive_int(record.get("team_id")),
        team_name=_optional_string(record.get("team_name")),
    )


def _player_candidate(record: dict[str, Any]) -> ProfessionalPlayerCandidate:
    return ProfessionalPlayerCandidate(**_player_reference(record).model_dump())


def _compile_pattern(value: str | None) -> regex.Pattern[str] | None:
    if value is None:
        return None
    try:
        return regex.compile(value)
    except regex.error as exc:
        raise ValueError("version_pattern must be a valid full-string expression") from exc


def _patch_filter(
    patches: list[dict[str, Any]], request: PlayerFantasyRequest, pattern: regex.Pattern[str] | None
) -> tuple[dict[int, str], str, regex.Pattern[str]]:
    names = {
        _positive_int(item.get("id") or item.get("patch")): str(
            item.get("name") or item.get("patch_name")
        )
        for item in patches
        if _positive_int(item.get("id") or item.get("patch"))
        and (item.get("name") or item.get("patch_name"))
    }
    dated = [
        (timestamp, str(item.get("name") or item.get("patch_name")))
        for item in patches
        if (timestamp := _release_timestamp(item.get("date"))) is not None
        and (item.get("name") or item.get("patch_name"))
    ]
    if not names:
        raise ValueError("OpenDota patch catalog contains no labels")
    if pattern is None:
        if not dated:
            raise ValueError("OpenDota patch catalog contains no dated labels")
        effective = max(dated)[1]
        pattern = regex.compile(regex.escape(effective))
    else:
        for label in names.values():
            _safe_fullmatch(pattern, label)
        effective = request.version_pattern or ""
    return {key: value for key, value in names.items() if key is not None}, effective, pattern


def _safe_fullmatch(pattern: regex.Pattern[str], value: str) -> bool:
    try:
        return pattern.fullmatch(value, timeout=0.05) is not None
    except TimeoutError as exc:
        raise ValueError("version_pattern evaluation timed out") from exc


def _league_references(values: list[dict[str, Any]]) -> dict[int, tuple[str, str]]:
    result: dict[int, tuple[str, str]] = {}
    for item in values:
        identifier = _positive_int(item.get("leagueid") or item.get("league_id") or item.get("id"))
        name, tier = _optional_string(item.get("name")), _optional_string(item.get("tier"))
        if identifier and name and tier:
            result[identifier] = (name, tier)
    return result


def _hero_references(values: list[dict[str, Any]]) -> dict[int, str]:
    return {
        identifier: str(item["localized_name"])
        for item in values
        if (identifier := _positive_int(item.get("id"))) and item.get("localized_name")
    }


def _summary_date_possible(summary: dict[str, Any], request: PlayerFantasyRequest) -> bool:
    timestamp = _number(summary.get("start_time"))
    if timestamp is None:
        return True
    day = datetime.fromtimestamp(timestamp, UTC).date()
    return not (
        (request.start_date and day < request.start_date)
        or (request.end_date and day > request.end_date)
    )


def _root_warnings(
    has_matches: bool, partial_failures: int, limit_reason: str | None
) -> list[DataWarning]:
    warnings: list[DataWarning] = []
    if has_matches:
        warnings.extend(
            [
                DataWarning(
                    code="madstone_unavailable",
                    message=(
                        "OpenDota does not expose verified per-player Madstones collected; "
                        "item-use events are not collection evidence."
                    ),
                ),
                DataWarning(
                    code="watchers_unavailable",
                    message=(
                        "OpenDota cannot distinguish the capture state needed for exact Watchers "
                        "Taken evidence."
                    ),
                ),
                DataWarning(
                    code="lotuses_unavailable",
                    message=(
                        "OpenDota does not expose compatible per-player lotus collection evidence."
                    ),
                ),
            ]
        )
    if partial_failures:
        warnings.append(
            DataWarning(
                code="partial_match_failures",
                message=(
                    f"{partial_failures} match detail record(s) failed safely and were omitted."
                ),
            )
        )
    if limit_reason:
        warnings.append(
            DataWarning(
                code=limit_reason,
                message=(
                    "A fixed collection safety limit was reached; additional eligible maps may "
                    "exist."
                ),
            )
        )
    return warnings


def _error(
    code: str, message: str, *, valid_values: list[str] | None = None
) -> PlayerFantasyResponse:
    return PlayerFantasyResponse(
        error=ToolErrorDetail(code=code, message=message, tool=TOOL_NAME, valid_values=valid_values)
    )


def _validation_message(exc: Exception) -> str:
    return str(exc).split("\n", 1)[0]


def _valid_values(exc: Exception) -> list[str] | None:
    return [FantasyInclude.FANTASY_SCORING.value] if "include" in str(exc) else None


def _is_radiant(row: dict[str, Any]) -> bool | None:
    if isinstance(row.get("isRadiant"), bool):
        return bool(row["isRadiant"])
    slot = _nonnegative_int(row.get("player_slot"))
    return slot < 128 if slot is not None else None


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _first_known_integer(*values: object) -> int | None:
    """Return the first compatible value without treating zero as absent."""
    return next(
        (number for value in values if (number := _nonnegative_int(value)) is not None), None
    )


def _number(value: object) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def _release_timestamp(value: object) -> float | None:
    numeric = _number(value)
    if numeric is not None:
        return numeric
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _nonnegative_number(value: object) -> float | None:
    number = _number(value)
    return number if number is not None and number >= 0 else None


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None and str(value).strip() else None


def _patch_tuple(value: str) -> tuple[int, int]:
    parts = value.split(".", 1)
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return (0, 0)
