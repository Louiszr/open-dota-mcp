"""Tournament and team match discovery with immutable continuation pages."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.errors import (
    DataWarning,
    ErrorStatus,
    ToolErrorDetail,
    UpstreamError,
    WarningStatus,
)
from open_dota_mcp.models.common import (
    LeagueIdentity,
    Side,
    TeamIdentity,
    TeamResult,
    Winner,
    utc_datetime,
)
from open_dota_mcp.models.discovery import (
    LeagueCandidate,
    TeamCandidate,
    TeamFilters,
    TeamMatchSummary,
    TeamResponse,
    TournamentMatchSummary,
    TournamentResponse,
)
from open_dota_mcp.pagination import PaginationError, SnapshotRegistry
from open_dota_mcp.services.identity import load_team_catalog, resolve_league, resolve_team


class MatchDiscoveryService:
    """Resolve professional identities and return stable bounded match pages."""

    def __init__(self, client: OpenDotaClient, registry: SnapshotRegistry) -> None:
        """Initialize discovery with shared HTTP and snapshot dependencies."""
        self.client = client
        self.registry = registry
        self._tournament_context: dict[str, tuple[LeagueIdentity, dict[str, Any]]] = {}
        self._team_context: dict[str, tuple[TeamIdentity, TeamFilters, dict[str, Any]]] = {}

    async def list_tournament_matches(
        self,
        *,
        league_id: int | None = None,
        tournament_name: str | None = None,
        page_size: int | None = None,
        continuation_token: str | None = None,
    ) -> TournamentResponse:
        """Resolve a professional league and return one immutable newest-first page."""
        tool = "list_pro_tournament_matches"
        if continuation_token:
            context = self._tournament_context.get(continuation_token)
            if context is None:
                return self._pagination_tournament_error(continuation_token, tool)
            league, saved_query = context
            supplied = _tournament_query(league_id, tournament_name, page_size)
            query = saved_query if not supplied else supplied
            try:
                items, page = self.registry.next_page(
                    continuation_token, tool=tool, query=query if supplied else None
                )
            except PaginationError as exc:
                return _tournament_error(tool, exc.code, str(exc), restart=exc.restart_required)
            self._tournament_context.pop(continuation_token, None)
            if page.continuation_token:
                self._tournament_context[page.continuation_token] = (league, saved_query)
            return TournamentResponse(league=league, matches=items, page=page)
        selector_error = _selector_error(league_id, tournament_name)
        if selector_error:
            return _tournament_error(tool, "invalid_selector", selector_error)
        try:
            effective_page_size = 20 if page_size is None else page_size
            self.registry._validate_page_size(effective_page_size)
            leagues = await self.client.get_leagues()
            raw_league = _find_by_id(leagues, "leagueid", league_id) if league_id else None
            if tournament_name is not None:
                resolution = resolve_league(tournament_name, leagues)
                if resolution.selected is None:
                    if resolution.candidates:
                        return TournamentResponse(
                            query=resolution.query,
                            candidates=[_league_candidate(item) for item in resolution.candidates],
                            warnings=[_selection_warning("Choose a league_id from the candidates")],
                        )
                    return _tournament_error(
                        tool, "identity_not_found", "No matching league was found"
                    )
                raw_league = resolution.selected
            if raw_league is None:
                return _tournament_error(tool, "identity_not_found", "No matching league was found")
            league = _league_identity(raw_league)
            if (league.tier or "").casefold() not in {"premium", "professional"}:
                return _tournament_error(
                    tool, "ineligible_league", "League is not eligible for professional discovery"
                )
            raw_matches = await self.client.get_league_matches(league.league_id)
            records = _tournament_records(raw_matches, league)
            query = {"league_id": league.league_id, "page_size": effective_page_size}
            items, page = self.registry.first_page(
                tool=tool, query=query, items=records, page_size=effective_page_size
            )
            if page.continuation_token:
                self._tournament_context[page.continuation_token] = (league, query)
            return TournamentResponse(league=league, matches=items, page=page)
        except asyncio.CancelledError:
            raise
        except PaginationError as exc:
            return _tournament_error(tool, exc.code, str(exc))
        except UpstreamError as exc:
            return TournamentResponse(error=exc.detail(tool))

    async def list_team_matches(
        self,
        *,
        team_id: int | None = None,
        team_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        side: str | None = None,
        result: str | None = None,
        page_size: int | None = None,
        continuation_token: str | None = None,
    ) -> TeamResponse:
        """Resolve a team and return one filtered immutable newest-first match page."""
        tool = "list_pro_team_matches"
        if continuation_token:
            context = self._team_context.get(continuation_token)
            if context is None:
                return self._pagination_team_error(continuation_token, tool)
            team, filters, saved_query = context
            supplied = _team_query(
                team_id, team_name, start_date, end_date, side, result, page_size
            )
            try:
                items, page = self.registry.next_page(
                    continuation_token,
                    tool=tool,
                    query=supplied if supplied else None,
                )
            except PaginationError as exc:
                return _team_error(tool, exc.code, str(exc), restart=exc.restart_required)
            self._team_context.pop(continuation_token, None)
            if page.continuation_token:
                self._team_context[page.continuation_token] = (team, filters, saved_query)
            return TeamResponse(team=team, filters=filters, matches=items, page=page)
        selector_error = _selector_error(team_id, team_name)
        if selector_error:
            return _team_error(tool, "invalid_selector", selector_error)
        try:
            effective_page_size = 20 if page_size is None else page_size
            self.registry._validate_page_size(effective_page_size)
            start, end, filters = _parse_filters(start_date, end_date, side, result)
            if team_name is not None:
                catalog = await load_team_catalog(self.client)
                resolution = resolve_team(team_name, catalog)
                if resolution.selected is None:
                    if resolution.candidates:
                        return TeamResponse(
                            query=resolution.query,
                            candidates=[_team_candidate(item) for item in resolution.candidates],
                            warnings=[_selection_warning("Choose a team_id from the candidates")],
                        )
                    return _team_error(tool, "identity_not_found", "No matching team was found")
                raw_team = resolution.selected
            else:
                raw_team = await self.client.get_team(int(team_id))
            team = _team_identity(raw_team)
            if team.team_id is None:
                return _team_error(tool, "identity_not_found", "No matching team was found")
            raw_matches = await self.client.get_team_matches(team.team_id)
            anomaly_warning = _anomalous_side_warning(raw_matches, team.team_id)
            records = _team_records(raw_matches, team, start, end, filters)
            query = {
                "team_id": team.team_id,
                "start_date": start_date,
                "end_date": end_date,
                "side": side,
                "result": result,
                "page_size": effective_page_size,
            }
            items, page = self.registry.first_page(
                tool=tool, query=query, items=records, page_size=effective_page_size
            )
            if page.continuation_token:
                self._team_context[page.continuation_token] = (team, filters, query)
            return TeamResponse(
                team=team,
                filters=filters,
                matches=items,
                page=page,
                warnings=[anomaly_warning] if anomaly_warning else None,
            )
        except asyncio.CancelledError:
            raise
        except (PaginationError, ValueError) as exc:
            code = exc.code if isinstance(exc, PaginationError) else "invalid_date"
            if "side" in str(exc) or "result" in str(exc):
                code = "invalid_filter"
            return _team_error(tool, code, str(exc))
        except UpstreamError as exc:
            return TeamResponse(error=exc.detail(tool))

    def _pagination_tournament_error(self, token: str, tool: str) -> TournamentResponse:
        try:
            self.registry.next_page(token, tool=tool)
        except PaginationError as exc:
            return _tournament_error(tool, exc.code, str(exc), restart=exc.restart_required)
        raise AssertionError("Continuation context and registry state diverged")

    def _pagination_team_error(self, token: str, tool: str) -> TeamResponse:
        try:
            self.registry.next_page(token, tool=tool)
        except PaginationError as exc:
            return _team_error(tool, exc.code, str(exc), restart=exc.restart_required)
        raise AssertionError("Continuation context and registry state diverged")


def _tournament_records(
    raw_matches: list[dict[str, Any]], league: LeagueIdentity
) -> list[TournamentMatchSummary]:
    unique = _collapse_duplicates(raw_matches)
    records: list[TournamentMatchSummary] = []
    for raw, conflict in unique:
        warnings = _record_warnings(raw, conflict)
        radiant_win = raw.get("radiant_win")
        records.append(
            TournamentMatchSummary(
                match_id=int(raw["match_id"]),
                start_time=utc_datetime(raw.get("start_time")),
                league=LeagueIdentity(
                    league_id=league.league_id,
                    name=raw.get("league_name") or league.name,
                    tier=league.tier,
                ),
                radiant_team=TeamIdentity(
                    team_id=_integer(raw.get("radiant_team_id")),
                    name=raw.get("radiant_team_name") or raw.get("radiant_name"),
                ),
                dire_team=TeamIdentity(
                    team_id=_integer(raw.get("dire_team_id")),
                    name=raw.get("dire_team_name") or raw.get("dire_name"),
                ),
                winner=(Winner.RADIANT if radiant_win else Winner.DIRE)
                if isinstance(radiant_win, bool)
                else None,
                radiant_score=_integer(raw.get("radiant_score")),
                dire_score=_integer(raw.get("dire_score")),
                warnings=warnings or None,
            )
        )
    return sorted(records, key=_record_sort, reverse=True)


def _team_records(
    raw_matches: list[dict[str, Any]],
    team: TeamIdentity,
    start: date | None,
    end: date | None,
    filters: TeamFilters,
) -> list[TeamMatchSummary]:
    records: list[TeamMatchSummary] = []
    for raw, conflict in _collapse_duplicates(raw_matches):
        selected_side = _team_match_side(raw, team.team_id)
        if selected_side is None:
            continue
        started = utc_datetime(raw.get("start_time"))
        if start and (started is None or started.date() < start):
            continue
        if end and (started is None or started.date() > end):
            continue
        radiant_win = raw.get("radiant_win")
        selected_result = None
        if isinstance(radiant_win, bool):
            won = radiant_win == (selected_side == Side.RADIANT)
            selected_result = TeamResult.WIN if won else TeamResult.LOSS
        if filters.side and filters.side != selected_side:
            continue
        if filters.result and filters.result != selected_result:
            continue
        opponent = _team_match_opponent(raw, selected_side)
        warnings = _record_warnings(raw, conflict)
        records.append(
            TeamMatchSummary(
                match_id=int(raw["match_id"]),
                start_time=started,
                league=LeagueIdentity(
                    league_id=_integer(raw.get("leagueid")) or 1,
                    name=raw.get("league_name"),
                    tier=raw.get("tier"),
                ),
                selected_team=team,
                opponent=opponent,
                selected_team_side=selected_side,
                selected_team_result=selected_result,
                radiant_score=_integer(raw.get("radiant_score")),
                dire_score=_integer(raw.get("dire_score")),
                warnings=warnings or None,
            )
        )
    return sorted(records, key=_record_sort, reverse=True)


def _anomalous_side_warning(raw_matches: list[dict[str, Any]], team_id: int) -> DataWarning | None:
    anomalous = any(_team_match_side(raw, team_id) is None for raw in raw_matches)
    return (
        DataWarning(
            code="anomalous_team_side",
            message="Records without exactly one selected-team side were excluded",
        )
        if anomalous
        else None
    )


def _team_match_side(raw: dict[str, Any], team_id: int | None) -> Side | None:
    """Resolve the selected team's side from the documented team-match projection."""
    radiant = raw.get("radiant")
    opponent_id = _integer(raw.get("opposing_team_id"))
    if isinstance(radiant, bool):
        if team_id is not None and opponent_id == team_id:
            return None
        return Side.RADIANT if radiant else Side.DIRE

    radiant_id = _integer(raw.get("radiant_team_id"))
    dire_id = _integer(raw.get("dire_team_id"))
    appearances = [radiant_id == team_id, dire_id == team_id]
    if sum(appearances) != 1:
        return None
    return Side.RADIANT if appearances[0] else Side.DIRE


def _team_match_opponent(raw: dict[str, Any], selected_side: Side) -> TeamIdentity:
    """Project the opponent from compact or full-side OpenDota match fields."""
    if "opposing_team_id" in raw or "opposing_team_name" in raw:
        return TeamIdentity(
            team_id=_integer(raw.get("opposing_team_id")),
            name=raw.get("opposing_team_name"),
        )
    return TeamIdentity(
        team_id=_integer(
            raw.get("dire_team_id") if selected_side == Side.RADIANT else raw.get("radiant_team_id")
        ),
        name=(raw.get("dire_team_name") or raw.get("dire_name"))
        if selected_side == Side.RADIANT
        else (raw.get("radiant_team_name") or raw.get("radiant_name")),
    )


def _parse_filters(
    start_date: str | None, end_date: str | None, side: str | None, result: str | None
) -> tuple[date | None, date | None, TeamFilters]:
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    except ValueError as exc:
        raise ValueError("Dates must use exact YYYY-MM-DD UTC format") from exc
    if start and end and start > end:
        raise ValueError("start_date must not be after end_date")
    if side not in {None, "radiant", "dire"}:
        raise ValueError("side must be radiant or dire")
    if result not in {None, "win", "loss"}:
        raise ValueError("result must be win or loss")
    return (
        start,
        end,
        TeamFilters(start_date=start_date, end_date=end_date, side=side, result=result),
    )


def _collapse_duplicates(
    records: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], bool]]:
    selected: dict[int, dict[str, Any]] = {}
    conflicts: set[int] = set()
    for record in records:
        match_id = _integer(record.get("match_id"))
        if match_id is None:
            continue
        if match_id in selected and selected[match_id] != record:
            conflicts.add(match_id)
            if _stable_record(record) < _stable_record(selected[match_id]):
                selected[match_id] = record
        else:
            selected.setdefault(match_id, record)
    return [(record, match_id in conflicts) for match_id, record in selected.items()]


def _record_warnings(raw: dict[str, Any], conflict: bool) -> list[DataWarning]:
    warnings: list[DataWarning] = []
    if conflict:
        warnings.append(
            DataWarning(
                code="inconsistent_duplicate_match",
                message="Conflicting duplicate record collapsed",
            )
        )
    if raw.get("radiant_win") is None:
        warnings.append(DataWarning(code="missing_result", message="Match winner is unavailable"))
    if raw.get("radiant_score") is None or raw.get("dire_score") is None:
        warnings.append(
            DataWarning(code="missing_score", message="One or more final scores are unavailable")
        )
    return warnings


def _record_sort(record: TournamentMatchSummary | TeamMatchSummary) -> tuple[float, int]:
    return (record.start_time.timestamp() if record.start_time else 0.0, record.match_id)


def _stable_record(record: dict[str, Any]) -> str:
    return repr(sorted(record.items(), key=lambda item: item[0]))


def _selector_error(identifier: int | None, name: str | None) -> str | None:
    if (identifier is None) == (name is None):
        return "Provide exactly one stable ID or name selector"
    if identifier is not None and (isinstance(identifier, bool) or identifier <= 0):
        return "Stable ID must be a positive integer"
    if name is not None and not name.strip():
        return "Name selector must not be blank"
    return None


def _find_by_id(
    records: list[dict[str, Any]], key: str, identifier: int | None
) -> dict[str, Any] | None:
    return next((item for item in records if _integer(item.get(key)) == identifier), None)


def _league_identity(raw: dict[str, Any]) -> LeagueIdentity:
    return LeagueIdentity(
        league_id=int(raw.get("leagueid") or raw.get("league_id")),
        name=raw.get("name"),
        tier=raw.get("tier"),
    )


def _team_identity(raw: dict[str, Any]) -> TeamIdentity:
    return TeamIdentity(
        team_id=_integer(raw.get("team_id")), name=raw.get("name"), tag=raw.get("tag")
    )


def _league_candidate(raw: dict[str, Any]) -> LeagueCandidate:
    identity = _league_identity(raw)
    return LeagueCandidate(**identity.model_dump())


def _team_candidate(raw: dict[str, Any]) -> TeamCandidate:
    return TeamCandidate(
        team_id=int(raw["team_id"]),
        name=raw.get("name"),
        tag=raw.get("tag"),
        last_match_time=utc_datetime(raw.get("last_match_time")),
    )


def _selection_warning(message: str) -> DataWarning:
    return DataWarning(
        status=WarningStatus.NEEDS_SELECTION, code="ambiguous_identity", message=message
    )


def _tournament_error(
    tool: str, code: str, message: str, *, restart: bool = False
) -> TournamentResponse:
    return TournamentResponse(
        error=ToolErrorDetail(
            status=ErrorStatus.ERROR,
            code=code,
            message=message,
            tool=tool,
            restart_required=True if restart else None,
        )
    )


def _team_error(tool: str, code: str, message: str, *, restart: bool = False) -> TeamResponse:
    return TeamResponse(
        error=ToolErrorDetail(
            status=ErrorStatus.ERROR,
            code=code,
            message=message,
            tool=tool,
            restart_required=True if restart else None,
        )
    )


def _tournament_query(
    league_id: int | None, tournament_name: str | None, page_size: int | None
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "league_id": league_id,
            "tournament_name": tournament_name,
            "page_size": page_size,
        }.items()
        if value is not None
    }


def _team_query(
    team_id: int | None,
    team_name: str | None,
    start_date: str | None,
    end_date: str | None,
    side: str | None,
    result: str | None,
    page_size: int | None,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "team_id": team_id,
            "team_name": team_name,
            "start_date": start_date,
            "end_date": end_date,
            "side": side,
            "result": result,
            "page_size": page_size,
        }.items()
        if value is not None
    }


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
