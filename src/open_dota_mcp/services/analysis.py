"""Team-relative professional drafting report orchestration and mapping."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import Any

import regex

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.errors import AnalysisErrorDetail, UpstreamError
from open_dota_mcp.models.analysis import (
    AnalysisDraftAction,
    AnalysisInclude,
    AnalysisToolResponse,
    AppliedFilters,
    BanOrder,
    DraftEvidence,
    DraftingReport,
    DraftingReportRequest,
    DraftMatchup,
    EconomyEvidence,
    FirstBanFilter,
    HeroTotalGold,
    LaneComparison,
    LaneEvidence,
    LookbackCoverage,
    MatchComparison,
    ObjectiveEvidence,
    ObjectiveTeamEvidence,
    StructureCheckpoints,
    StructureEvidence,
    TeamReference,
    TournamentReference,
    TournamentTier,
)
from open_dota_mcp.models.common import Side, TeamResult, utc_datetime
from open_dota_mcp.pagination import PaginationError, SnapshotRegistry
from open_dota_mcp.services.drafts import (
    authoritative_draft_actions,
    draft_action_rounds,
    hero_lane_opponents,
    unique_player_for_hero,
)

TOOL_NAME = "analyze_pro_team_drafts"
TIER_VALUES = tuple(value.value for value in TournamentTier)
INCLUDE_VALUES = tuple(value.value for value in AnalysisInclude)
SIDE_VALUES = tuple(value.value for value in Side)
RESULT_VALUES = tuple(value.value for value in TeamResult)
FIRST_BAN_VALUES = tuple(value.value for value in FirstBanFilter)
LANE_NAMES = {1: "safelane", 2: "midlane", 3: "offlane"}
ROSHAN_TYPES = {"CHAT_MESSAGE_ROSHAN_KILL", "roshan_kill"}
TORMENTOR_TYPES = {"CHAT_MESSAGE_MINIBOSS_KILL", "miniboss_kill", "tormentor_kill"}


class AnalysisValidationError(ValueError):
    """A concise classified request validation failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        valid_values: list[str] | None = None,
        restart_required: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.detail = AnalysisErrorDetail(
            code=code,
            message=message,
            valid_values=valid_values,
            restart_required=restart_required,
        )


class AnalysisService:
    """Build immutable, bounded drafting reports from OpenDota records."""

    def __init__(
        self,
        client: OpenDotaClient,
        registry: SnapshotRegistry,
        *,
        concurrency: int = 5,
    ) -> None:
        """Initialize upstream and traversal dependencies."""
        if concurrency <= 0:
            raise ValueError("concurrency must be positive")
        self.client = client
        self.registry = registry
        self._semaphore = asyncio.Semaphore(min(concurrency, 5))

    async def analyze(
        self,
        *,
        team_id: int | None = None,
        lookback_count: int | None = None,
        version_pattern: str | None = None,
        tournament_tiers: list[str] | None = None,
        side: str | None = None,
        result: str | None = None,
        first_ban: str | None = None,
        include: list[str] | None = None,
        page_size: int | None = None,
        continuation_cursor: str | None = None,
    ) -> AnalysisToolResponse:
        """Return a first report page or consume an immutable continuation cursor."""
        raw = {
            "team_id": team_id,
            "lookback_count": lookback_count,
            "version_pattern": version_pattern,
            "tournament_tiers": tournament_tiers,
            "side": side,
            "result": result,
            "first_ban": first_ban,
            "include": include,
            "page_size": page_size,
        }
        try:
            if continuation_cursor is not None:
                query = None
                if any(value is not None for value in raw.values()):
                    request, _pattern = normalize_request(**raw)
                    query = request.model_dump(mode="json")
                page, metadata, context = self.registry.next_page_with_context(
                    continuation_cursor,
                    tool=TOOL_NAME,
                    query=query,
                )
                report = DraftingReport(
                    **context,
                    matches=page,
                    next_cursor=metadata.continuation_token,
                )
                return AnalysisToolResponse.from_report(report)

            request, pattern = normalize_request(**raw)
            return AnalysisToolResponse.from_report(await self._first_page(request, pattern))
        except AnalysisValidationError as exc:
            return AnalysisToolResponse(error=exc.detail)
        except PaginationError as exc:
            return AnalysisToolResponse(
                error=AnalysisErrorDetail(
                    code=exc.code,
                    message=str(exc),
                    restart_required=True if exc.restart_required else None,
                )
            )
        except UpstreamError as exc:
            return AnalysisToolResponse(error=exc.analysis_detail())

    async def _first_page(
        self,
        request: DraftingReportRequest,
        pattern: regex.Pattern[str] | None,
    ) -> DraftingReport:
        try:
            team = await self.client.get_team(request.team_id)
        except UpstreamError as exc:
            if exc.status_code == 404:
                raise AnalysisValidationError(
                    "identity_not_found",
                    "Team identity was not found; use the existing team lookup tool",
                ) from None
            raise
        patches_task = self.client.get_patches()
        history_task = self.client.get_team_matches(request.team_id)
        leagues_task = self.client.get_leagues()
        heroes_task = self.client.get_heroes()
        players_task = self.client.get_pro_players()
        reference_results = await asyncio.gather(
            patches_task,
            history_task,
            leagues_task,
            heroes_task,
            players_task,
            return_exceptions=True,
        )
        patches_result, history_result, leagues_result, heroes_result, professionals_result = (
            reference_results
        )
        if isinstance(patches_result, BaseException):
            raise patches_result
        if isinstance(history_result, BaseException):
            raise history_result
        patches = patches_result
        history = history_result
        leagues = [] if isinstance(leagues_result, BaseException) else leagues_result
        heroes = [] if isinstance(heroes_result, BaseException) else heroes_result
        professionals = (
            [] if isinstance(professionals_result, BaseException) else professionals_result
        )
        identity = _team_reference(team, request.team_id)
        patch_names, patch_dates = _patch_references(patches)
        applied_patch, pattern = _resolve_patch(
            pattern, request.version_pattern, patch_names, patches
        )
        _validate_pattern_catalog(pattern, patch_names.values())
        quota = normalize_completed_matches(history)[: request.lookback_count]
        details = await asyncio.gather(
            *(self._get_detail(_integer(item.get("match_id"))) for item in quota),
            return_exceptions=True,
        )
        hero_names = _hero_references(heroes)
        professional_names = _professional_references(professionals)
        league_refs = _league_references(leagues)
        parsed = 0
        matches: list[MatchComparison] = []
        groups = set(request.include)
        for summary, detail in zip(quota, details, strict=True):
            expected_match_id = _integer(summary.get("match_id"))
            if isinstance(detail, BaseException) or not _is_usable_parsed(
                detail, expected_match_id
            ):
                continue
            parsed += 1
            comparison = map_match_comparison(
                detail,
                summary=summary,
                team_id=request.team_id,
                patch_names=patch_names,
                patch_dates=patch_dates,
                league_refs=league_refs,
                hero_names=hero_names,
                professional_names=professional_names,
                include=groups,
            )
            if comparison is None:
                continue
            if _matches_filters(comparison, request, pattern):
                matches.append(comparison)
        matches.sort(key=lambda item: (item.start_time, item.match_id), reverse=True)
        coverage = LookbackCoverage(
            examined=len(quota),
            parsed=parsed,
            unparsed=len(quota) - parsed,
        )
        filters = AppliedFilters(
            patch=applied_patch,
            tournament_tiers=list(request.tournament_tiers),
            side=request.side,
            result=request.result,
            first_ban=request.first_ban,
        )
        context = {
            "team": identity.model_dump(),
            "filters": filters.model_dump(),
            "coverage": coverage.model_dump(),
        }
        page, metadata = self.registry.first_page(
            tool=TOOL_NAME,
            query=request.model_dump(mode="json"),
            items=matches,
            page_size=request.page_size,
            context=context,
        )
        return DraftingReport(
            team=identity,
            filters=filters,
            coverage=coverage,
            matches=page,
            next_cursor=metadata.continuation_token,
        )

    async def _get_detail(self, match_id: int | None) -> dict[str, Any]:
        if match_id is None:
            raise ValueError("invalid match identity")
        async with self._semaphore:
            return await self.client.get_match(match_id)


def normalize_request(
    *,
    team_id: int | None,
    lookback_count: int | None,
    version_pattern: str | None,
    tournament_tiers: list[str] | None,
    side: str | None,
    result: str | None,
    first_ban: str | None,
    include: list[str] | None,
    page_size: int | None,
) -> tuple[DraftingReportRequest, regex.Pattern[str] | None]:
    """Validate and canonicalize all public first-page inputs before any I/O."""
    if isinstance(team_id, bool) or not isinstance(team_id, int) or team_id <= 0:
        raise AnalysisValidationError("invalid_team_id", "Use a positive stable team ID")
    lookback = 25 if lookback_count is None else lookback_count
    if isinstance(lookback, bool) or not isinstance(lookback, int) or not 1 <= lookback <= 100:
        raise AnalysisValidationError("invalid_lookback_count", "lookback_count must be 1-100")
    size = 10 if page_size is None else page_size
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 25:
        raise AnalysisValidationError("invalid_page_size", "page_size must be 1-25")
    tiers = _distinct_values(
        tournament_tiers if tournament_tiers is not None else ["premium"],
        name="tournament_tiers",
        allowed=TIER_VALUES,
        code="invalid_tournament_tiers",
    )
    if not tiers or "all" in tiers and len(tiers) != 1:
        raise AnalysisValidationError(
            "invalid_tournament_tiers",
            "Use one or more named tiers, or all by itself",
            valid_values=list(TIER_VALUES),
        )
    groups = _distinct_values(
        include or [], name="include", allowed=INCLUDE_VALUES, code="invalid_include"
    )
    normalized_side = _enum_value(side, SIDE_VALUES, "side")
    normalized_result = _enum_value(result, RESULT_VALUES, "result")
    normalized_first_ban = _enum_value(first_ban, FIRST_BAN_VALUES, "first_ban")
    compiled = _compile_pattern(version_pattern)
    request = DraftingReportRequest(
        team_id=team_id,
        lookback_count=lookback,
        version_pattern=version_pattern,
        tournament_tiers=tiers,
        side=normalized_side,
        result=normalized_result,
        first_ban=normalized_first_ban,
        include=groups,
        page_size=size,
    )
    return request, compiled


def normalize_completed_matches(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return unique completed match summaries newest first."""
    completed = [
        item
        for item in history
        if _integer(item.get("match_id")) is not None
        and _number(item.get("start_time")) is not None
        and _number(item.get("duration")) is not None
        and float(item["duration"]) >= 0
    ]
    completed.sort(
        key=lambda item: (float(item["start_time"]), int(item["match_id"])), reverse=True
    )
    return list({int(item["match_id"]): item for item in completed}.values())


def map_match_comparison(
    raw: dict[str, Any],
    *,
    summary: dict[str, Any],
    team_id: int,
    patch_names: dict[int, str],
    patch_dates: dict[int, float],
    league_refs: dict[int, tuple[str, str]],
    hero_names: dict[int, str],
    professional_names: dict[int, str],
    include: set[str],
) -> MatchComparison | None:
    """Project one parsed match from the selected team's perspective."""
    placement = _team_placement(raw, team_id)
    match_id = _integer(raw.get("match_id"))
    start_time = utc_datetime(_number(raw.get("start_time")))
    duration = _integer(raw.get("duration"))
    patch_id = _integer(raw.get("patch"))
    league_id = _integer(raw.get("leagueid"))
    if (
        placement is None
        or match_id is None
        or match_id <= 0
        or start_time is None
        or duration is None
        or duration < 0
        or patch_id not in patch_names
    ):
        return None
    side, analyzed_name, opponent_id, opponent_name = placement
    radiant_win = raw.get("radiant_win")
    if (
        not isinstance(radiant_win, bool)
        or opponent_id is None
        or opponent_id <= 0
        or not analyzed_name
        or not opponent_name
    ):
        return None
    result = TeamResult.WIN if radiant_win == (side == Side.RADIANT) else TeamResult.LOSS
    league = raw.get("league") if isinstance(raw.get("league"), dict) else {}
    fallback_name, fallback_tier = league_refs.get(league_id or -1, ("", ""))
    tournament_name = str(league.get("name") or summary.get("league_name") or fallback_name)
    tournament_tier = str(league.get("tier") or fallback_tier)
    if not tournament_name or not tournament_tier:
        return None
    comparison = MatchComparison(
        match_id=match_id,
        start_time=start_time,
        duration_seconds=duration,
        tournament=TournamentReference(name=tournament_name, tier=tournament_tier),
        patch=patch_names[patch_id],
        analyzed_team=analyzed_name,
        opponent=TeamReference(team_id=opponent_id, name=opponent_name),
        side=side,
        result=result,
        ban_order=_ban_order(raw, side),
    )
    if "draft" in include:
        comparison.draft = _draft_evidence(
            raw, side, analyzed_name, opponent_name, hero_names, professional_names
        )
    if "lanes" in include:
        comparison.lanes = _lane_evidence(raw, side, hero_names, duration)
    if "economy" in include:
        comparison.economy = _economy_evidence(
            raw, side, analyzed_name, opponent_name, hero_names, professional_names
        )
    if "structures" in include:
        comparison.structures = _structure_evidence(raw, side, duration)
    if "objectives" in include:
        comparison.objectives = _objective_evidence(
            raw, side, duration, patch_id, patch_names, patch_dates
        )
    return comparison


def _matches_filters(
    match: MatchComparison,
    request: DraftingReportRequest,
    pattern: regex.Pattern[str] | None,
) -> bool:
    tiers = set(request.tournament_tiers)
    if "all" not in tiers and match.tournament.tier not in tiers:
        return False
    if pattern is not None and not _safe_fullmatch(pattern, match.patch):
        return False
    if request.side is not None and match.side != request.side:
        return False
    if request.result is not None and match.result != request.result:
        return False
    if request.first_ban is not None:
        expected = BanOrder.FIRST if request.first_ban == FirstBanFilter.YES else BanOrder.SECOND
        if match.ban_order != expected:
            return False
    return True


def _draft_evidence(
    raw: dict[str, Any],
    analyzed_side: Side,
    analyzed_name: str,
    opponent_name: str,
    heroes: dict[int, str],
    professionals: dict[int, str],
) -> DraftEvidence:
    ordered, authoritative = _ordered_actions(raw)
    players = [value for value in raw.get("players", []) if isinstance(value, dict)]
    rounds = draft_action_rounds(ordered) if authoritative else {}
    mapped: list[AnalysisDraftAction] = []
    for action in ordered:
        order = _integer(action.get("order"))
        team = _integer(action.get("team"))
        hero_id = _integer(action.get("hero_id"))
        if order is None or team not in {0, 1} or hero_id not in heroes:
            continue
        side = Side.RADIANT if team == 0 else Side.DIRE
        is_pick = action.get("is_pick") is True
        player = unique_player_for_hero(players, hero_id, side) if is_pick else None
        player_name = _player_name(player, professionals) if player is not None else None
        matchup = None
        if authoritative and player is not None:
            lane = _lane_name(player)
            opposing = hero_lane_opponents(players, side, _lane_role(player))
            if lane is not None and opposing:
                known_ids = {
                    _integer(value.get("hero_id"))
                    for value in ordered
                    if value.get("is_pick") is True
                    and _integer(value.get("team")) == (1 if side == Side.RADIANT else 0)
                    and _integer(value.get("order")) is not None
                    and int(value["order"]) < order
                }
                matchup = DraftMatchup(
                    known=True,
                    lane=lane,
                    opposing_heroes=[
                        heroes[hero]
                        for value in opposing
                        if (hero := _integer(value.get("hero_id"))) in heroes and hero in known_ids
                    ],
                )
        mapped.append(
            AnalysisDraftAction(
                order=order,
                type="pick" if is_pick else "ban",
                round=rounds.get(id(action)) or None,
                team=analyzed_name if side == analyzed_side else opponent_name,
                hero=heroes[hero_id],
                player=player_name,
                matchup=matchup,
            )
        )
    return DraftEvidence(actions=mapped)


def _lane_evidence(
    raw: dict[str, Any], side: Side, heroes: dict[int, str], duration: int
) -> LaneEvidence:
    players = [value for value in raw.get("players", []) if isinstance(value, dict)]
    comparisons: list[LaneComparison] = []
    for role, lane in LANE_NAMES.items():
        analyzed = [
            value for value in players if _player_side(value) == side and _lane_role(value) == role
        ]
        opponents = [
            value
            for value in players
            if _player_side(value) == _opposite(side) and _lane_role(value) == role
        ]
        if not analyzed and not opponents:
            continue
        comparisons.append(
            LaneComparison(
                lane=lane,
                analyzed_team_heroes=_hero_labels(analyzed, heroes),
                opponent_heroes=_hero_labels(opponents, heroes),
                experience_difference_10=_series_difference(analyzed, opponents, "xp_t", 600)
                if duration >= 600
                else None,
                last_hit_difference_10=_series_difference(analyzed, opponents, "lh_t", 600)
                if duration >= 600
                else None,
            )
        )
    return LaneEvidence(lanes=comparisons)


def _economy_evidence(
    raw: dict[str, Any],
    side: Side,
    analyzed_name: str,
    opponent_name: str,
    heroes: dict[int, str],
    professionals: dict[int, str],
) -> EconomyEvidence:
    duration = _integer(raw.get("duration")) or 0
    advantage = raw.get("radiant_gold_adv")
    sign = 1 if side == Side.RADIANT else -1
    players = [value for value in raw.get("players", []) if isinstance(value, dict)]
    observations: list[HeroTotalGold] = []
    for player in players:
        hero_id = _integer(player.get("hero_id"))
        player_side = _player_side(player)
        if hero_id not in heroes or player_side is None:
            continue
        observations.append(
            HeroTotalGold(
                hero=heroes[hero_id],
                player=_player_name(player, professionals),
                team=analyzed_name if player_side == side else opponent_name,
                at_10=_sample_player(player, "gold_t", 600) if duration >= 600 else None,
                at_20=_sample_player(player, "gold_t", 1200) if duration >= 1200 else None,
            )
        )
    return EconomyEvidence(
        gold_difference_10=_signed_minute_sample(advantage, 10, sign) if duration >= 600 else None,
        gold_difference_20=_signed_minute_sample(advantage, 20, sign) if duration >= 1200 else None,
        hero_total_gold=observations,
    )


def _structure_evidence(raw: dict[str, Any], side: Side, duration: int) -> StructureEvidence:
    objectives = raw.get("objectives")
    if not isinstance(objectives, list):
        unknown = StructureCheckpoints(by_10=None, by_20=None)
        return StructureEvidence(analyzed_team_lost=unknown, opponent_lost=unknown.model_copy())
    losses: dict[Side, list[tuple[int, str]]] = {Side.RADIANT: [], Side.DIRE: []}
    for event in objectives:
        if not isinstance(event, dict) or event.get("type") != "building_kill":
            continue
        mapped = _structure_key(str(event.get("key", "")))
        event_time = _integer(event.get("time"))
        if mapped is not None and event_time is not None and event_time >= 0:
            owner, key = mapped
            losses[owner].append((event_time, key))

    def checkpoints(owner: Side) -> StructureCheckpoints:
        return StructureCheckpoints(
            by_10=_cumulative_keys(losses[owner], 600) if duration >= 600 else None,
            by_20=_cumulative_keys(losses[owner], 1200) if duration >= 1200 else None,
        )

    return StructureEvidence(
        analyzed_team_lost=checkpoints(side),
        opponent_lost=checkpoints(_opposite(side)),
    )


def _objective_evidence(
    raw: dict[str, Any],
    side: Side,
    duration: int,
    patch_id: int,
    patch_names: dict[int, str],
    patch_dates: dict[int, float],
) -> ObjectiveEvidence:
    objectives = raw.get("objectives")
    tormentor_applicable = _tormentor_applicable(patch_id, patch_names, patch_dates)
    if not isinstance(objectives, list):
        unknown = ObjectiveTeamEvidence(roshan_by_25=None, tormentor_by_25=None)
        return ObjectiveEvidence(analyzed_team=unknown, opponent=unknown.model_copy())
    limit = min(duration, 1500)
    events: dict[Side, dict[str, list[int]]] = {
        Side.RADIANT: {"roshan": [], "tormentor": []},
        Side.DIRE: {"roshan": [], "tormentor": []},
    }
    for event in objectives:
        if not isinstance(event, dict):
            continue
        event_time = _integer(event.get("time"))
        team = _integer(event.get("team"))
        event_side = Side.RADIANT if team in {0, 2} else Side.DIRE if team in {1, 3} else None
        event_type = event.get("type")
        if event_time is None or not 0 <= event_time <= limit or event_side is None:
            continue
        if event_type in ROSHAN_TYPES:
            events[event_side]["roshan"].append(event_time)
        elif event_type in TORMENTOR_TYPES:
            events[event_side]["tormentor"].append(event_time)

    def team_evidence(team_side: Side) -> ObjectiveTeamEvidence:
        return ObjectiveTeamEvidence(
            roshan_by_25=sorted(events[team_side]["roshan"]),
            tormentor_by_25=(
                sorted(events[team_side]["tormentor"]) if tormentor_applicable else None
            ),
        )

    return ObjectiveEvidence(
        analyzed_team=team_evidence(side),
        opponent=team_evidence(_opposite(side)),
    )


def _compile_pattern(value: str | None) -> regex.Pattern[str] | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise AnalysisValidationError(
            "invalid_version_expression",
            "Use a nonblank full-string patch expression of at most 64 characters",
        )
    try:
        return regex.compile(value)
    except regex.error:
        raise AnalysisValidationError(
            "invalid_version_expression", "Correct or simplify the patch expression"
        ) from None


def _safe_fullmatch(pattern: regex.Pattern[str], value: str) -> bool:
    try:
        return pattern.fullmatch(value, timeout=0.05) is not None
    except TimeoutError:
        raise AnalysisValidationError(
            "invalid_version_expression", "Simplify the patch expression; evaluation timed out"
        ) from None


def _validate_pattern_catalog(pattern: regex.Pattern[str] | None, labels: Any) -> None:
    if pattern is not None:
        for label in labels:
            _safe_fullmatch(pattern, label)


def _resolve_patch(
    pattern: regex.Pattern[str] | None,
    original: str | None,
    names: dict[int, str],
    patches: list[dict[str, Any]],
) -> tuple[str, regex.Pattern[str]]:
    if pattern is not None and original is not None:
        return original, pattern
    dated = [
        (_release_timestamp(item.get("date")), _patch_id(item), _patch_name(item))
        for item in patches
    ]
    valid = [value for value in dated if value[0] is not None and value[1] in names and value[2]]
    if not valid:
        raise AnalysisValidationError(
            "patch_catalog_unavailable",
            "Supply a version_pattern or retry when the dated patch catalog is available",
        )
    _date, _identifier, label = max(valid, key=lambda value: float(value[0]))
    assert label is not None
    return label, regex.compile(regex.escape(label))


def _team_reference(raw: dict[str, Any], requested_id: int) -> TeamReference:
    identifier = _integer(raw.get("team_id")) or _integer(raw.get("id"))
    name = raw.get("name")
    if identifier != requested_id or not isinstance(name, str) or not name:
        raise AnalysisValidationError(
            "identity_not_found", "Team identity was not found; use the existing team lookup tool"
        )
    return TeamReference(team_id=identifier, name=name)


def _team_placement(raw: dict[str, Any], team_id: int) -> tuple[Side, str, int | None, str] | None:
    radiant_id = _integer(raw.get("radiant_team_id"))
    dire_id = _integer(raw.get("dire_team_id"))
    if (radiant_id == team_id) == (dire_id == team_id):
        return None
    if radiant_id == team_id:
        return (
            Side.RADIANT,
            str(raw.get("radiant_name") or ""),
            dire_id,
            str(raw.get("dire_name") or ""),
        )
    return (
        Side.DIRE,
        str(raw.get("dire_name") or ""),
        radiant_id,
        str(raw.get("radiant_name") or ""),
    )


def _ban_order(raw: dict[str, Any], side: Side) -> BanOrder | None:
    actions, authoritative = _ordered_actions(raw)
    if not authoritative:
        return None
    bans = [
        value
        for value in actions
        if value.get("is_pick") is False and _integer(value.get("team")) in {0, 1}
    ]
    if not bans:
        return None
    first_side = Side.RADIANT if bans[0]["team"] == 0 else Side.DIRE
    return BanOrder.FIRST if first_side == side else BanOrder.SECOND


def _ordered_actions(raw: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    return authoritative_draft_actions(raw)


def _is_usable_parsed(value: Any, expected_match_id: int | None) -> bool:
    return (
        isinstance(value, dict)
        and expected_match_id is not None
        and _integer(value.get("match_id")) == expected_match_id
        and (_integer(value.get("version")) or 0) > 0
    )


def _distinct_values(
    values: list[str], *, name: str, allowed: tuple[str, ...], code: str
) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise AnalysisValidationError(code, f"{name} must be a list", valid_values=list(allowed))
    if len(values) != len(set(values)) or any(value not in allowed for value in values):
        raise AnalysisValidationError(
            code, f"Use distinct supported {name} values", valid_values=list(allowed)
        )
    return values


def _enum_value(value: str | None, allowed: tuple[str, ...], name: str) -> str | None:
    if value is not None and value not in allowed:
        raise AnalysisValidationError(
            "invalid_filter", f"Unsupported {name} filter", valid_values=list(allowed)
        )
    return value


def _patch_references(patches: list[dict[str, Any]]) -> tuple[dict[int, str], dict[int, float]]:
    names: dict[int, str] = {}
    dates: dict[int, float] = {}
    for item in patches:
        identifier = _patch_id(item)
        name = _patch_name(item)
        date = _release_timestamp(item.get("date"))
        if identifier is not None and name:
            names[identifier] = name
            if date is not None:
                dates[identifier] = float(date)
    return names, dates


def _patch_id(item: dict[str, Any]) -> int | None:
    return _integer(item.get("id")) or _integer(item.get("patch"))


def _patch_name(item: dict[str, Any]) -> str | None:
    value = item.get("name") or item.get("patch_name")
    return str(value) if value else None


def _hero_references(values: list[dict[str, Any]]) -> dict[int, str]:
    return {
        identifier: str(value["localized_name"])
        for value in values
        if (identifier := _integer(value.get("id"))) is not None and value.get("localized_name")
    }


def _professional_references(values: list[dict[str, Any]]) -> dict[int, str]:
    return {
        identifier: str(value["name"])
        for value in values
        if (identifier := _integer(value.get("account_id"))) is not None and value.get("name")
    }


def _league_references(values: list[dict[str, Any]]) -> dict[int, tuple[str, str]]:
    return {
        identifier: (str(value.get("name") or ""), str(value.get("tier") or ""))
        for value in values
        if (
            identifier := _integer(value.get("leagueid"))
            or _integer(value.get("league_id"))
            or _integer(value.get("id"))
        )
        is not None
    }


def _player_side(player: dict[str, Any]) -> Side | None:
    if isinstance(player.get("isRadiant"), bool):
        return Side.RADIANT if player["isRadiant"] else Side.DIRE
    slot = _integer(player.get("player_slot"))
    return (
        Side.RADIANT if slot is not None and slot < 128 else Side.DIRE if slot is not None else None
    )


def _opposite(side: Side) -> Side:
    return Side.DIRE if side == Side.RADIANT else Side.RADIANT


def _lane_role(player: dict[str, Any]) -> int | None:
    role = _integer(player.get("lane_role")) or _integer(player.get("lane"))
    return role if role in LANE_NAMES else None


def _lane_name(player: dict[str, Any]) -> str | None:
    role = _lane_role(player)
    return LANE_NAMES.get(role) if role is not None else None


def _player_name(player: dict[str, Any] | None, professionals: dict[int, str]) -> str | None:
    if player is None:
        return None
    account_id = _integer(player.get("account_id"))
    value = player.get("name") or professionals.get(account_id or -1)
    return str(value) if value else None


def _hero_labels(players: list[dict[str, Any]], heroes: dict[int, str]) -> list[str]:
    return [
        heroes[identifier]
        for value in players
        if (identifier := _integer(value.get("hero_id"))) in heroes
    ]


def _sample_player(player: dict[str, Any], field: str, checkpoint: int) -> int | None:
    times = player.get("times")
    values = player.get(field)
    if not isinstance(times, list) or not isinstance(values, list):
        return None
    indices = [
        index
        for index, value in enumerate(times[: len(values)])
        if _number(value) is not None and float(value) <= checkpoint
    ]
    if not indices:
        return None
    value = _number(values[max(indices)])
    return int(value) if value is not None else None


def _series_difference(
    analyzed: list[dict[str, Any]], opponents: list[dict[str, Any]], field: str, checkpoint: int
) -> int | None:
    analyzed_values = [_sample_player(value, field, checkpoint) for value in analyzed]
    opponent_values = [_sample_player(value, field, checkpoint) for value in opponents]
    if (
        not analyzed_values
        or not opponent_values
        or any(value is None for value in analyzed_values + opponent_values)
    ):
        return None
    return sum(analyzed_values) - sum(opponent_values)  # type: ignore[arg-type]


def _minute_sample(values: Any, minute: int) -> int | None:
    if not isinstance(values, list) or minute >= len(values):
        return None
    value = _number(values[minute])
    return int(value) if value is not None else None


def _signed_minute_sample(values: Any, minute: int, sign: int) -> int | None:
    value = _minute_sample(values, minute)
    return sign * value if value is not None else None


def _structure_key(raw: str) -> tuple[Side, str] | None:
    side = Side.RADIANT if "goodguys" in raw else Side.DIRE if "badguys" in raw else None
    if side is None:
        return None
    lane = (
        "bottom"
        if "bot" in raw
        else next((value for value in ("top", "mid") if value in raw), None)
    )
    if "tower4" in raw:
        key = "tier4"
    elif "tower" in raw and lane is not None:
        tier = next((value for value in ("1", "2", "3") if f"tower{value}" in raw), None)
        key = f"{lane}_t{tier}" if tier else None
    elif ("rax" in raw or "barracks" in raw) and lane is not None:
        kind = "melee_barracks" if "melee" in raw else "ranged_barracks" if "range" in raw else None
        key = f"{lane}_{kind}" if kind else None
    else:
        key = None
    return (side, key) if key else None


def _cumulative_keys(events: list[tuple[int, str]], checkpoint: int) -> list[str]:
    return list(
        dict.fromkeys(key for event_time, key in sorted(events) if event_time <= checkpoint)
    )


def _tormentor_applicable(patch_id: int, names: dict[int, str], dates: dict[int, float]) -> bool:
    boundary_ids = [
        identifier for identifier, name in names.items() if name == "7.33" and identifier in dates
    ]
    return bool(boundary_ids and patch_id in dates and dates[patch_id] >= dates[boundary_ids[0]])


def _number(value: Any) -> int | float | None:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def _release_timestamp(value: Any) -> float | None:
    numeric = _number(value)
    if numeric is not None:
        return float(numeric)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
