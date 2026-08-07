"""Latest-observed professional team lineup resolution."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.errors import DataWarning, ToolErrorDetail, UpstreamError
from open_dota_mcp.models.roster import (
    LatestObservedLineupResponse,
    LineupCoverage,
    LineupPlayer,
    LineupSourceMatch,
    RosterTeamCandidate,
    RosterTeamReference,
    TeamRosterRequest,
)
from open_dota_mcp.services.identity import load_team_catalog, resolve_team

TOOL_NAME = "get_pro_team_roster"
LANES = {1: "safelane", 2: "midlane", 3: "offlane"}


class RosterService:
    """Resolve a cross-checked five-player latest-observed lineup."""

    def __init__(self, client: OpenDotaClient) -> None:
        """Initialize the service with a typed OpenDota client."""
        self.client = client

    async def get_roster(
        self, *, team_id: int | None = None, team_name: str | None = None
    ) -> LatestObservedLineupResponse:
        """Return a verified lineup or bounded cannot-infer outcome."""
        try:
            request = TeamRosterRequest(team_id=team_id, team_name=team_name)
        except ValidationError as exc:
            return _error("invalid_request", str(exc).split("\n", 1)[0])
        try:
            team_or_response = await self._resolve_team(request)
            if isinstance(team_or_response, LatestObservedLineupResponse):
                return team_or_response
            team = team_or_response
            members_result, history_result, professionals_result = await asyncio.gather(
                self.client.get_team_players(team.team_id),
                self.client.get_team_matches(team.team_id),
                self.client.get_pro_players(),
                return_exceptions=True,
            )
            for result in (members_result, history_result):
                if isinstance(result, BaseException):
                    raise result
            members = _current_members(members_result)
            if members is None:
                return LatestObservedLineupResponse(
                    team=team,
                    coverage=LineupCoverage(
                        completed_records_considered=0, details_requested=0, parsed_usable=0
                    ),
                    error=_detail(
                        "current_roster_unavailable",
                        "OpenDota does not establish exactly five explicit current team members.",
                    ),
                )
            professionals = (
                [] if isinstance(professionals_result, BaseException) else professionals_result
            )
            return await self._scan(team, history_result, members, professionals)
        except asyncio.CancelledError:
            raise
        except UpstreamError as exc:
            return LatestObservedLineupResponse(error=exc.detail(TOOL_NAME))
        except (ValueError, TypeError) as exc:
            return _error("upstream_contract", str(exc))

    async def _resolve_team(
        self, request: TeamRosterRequest
    ) -> RosterTeamReference | LatestObservedLineupResponse:
        if request.team_id is not None:
            try:
                record = await self.client.get_team(request.team_id)
            except UpstreamError as exc:
                if exc.status_code == 404:
                    return _error("identity_not_found", "The professional team was not found")
                raise
            return _team_reference(record, request.team_id)
        assert request.team_name is not None
        catalog = await load_team_catalog(self.client)
        resolution = resolve_team(request.team_name, catalog)
        if not resolution.query:
            return _error("invalid_team_name", "team_name must contain letters or digits")
        if resolution.selected is None:
            if not resolution.candidates:
                return _error("identity_not_found", "No professional team matched that name or tag")
            return LatestObservedLineupResponse(
                candidates=[_team_candidate(item) for item in resolution.candidates]
            )
        return _team_reference(resolution.selected)

    async def _scan(
        self,
        team: RosterTeamReference,
        history: list[dict[str, Any]],
        current_members: set[int],
        professionals: list[dict[str, Any]],
    ) -> LatestObservedLineupResponse:
        completed = _completed_history(history)[:5]
        requested = 0
        for considered, summary in enumerate(completed, start=1):
            match_id = _positive_int(summary.get("match_id"))
            assert match_id is not None
            requested += 1
            try:
                detail = await self.client.get_match(match_id)
            except asyncio.CancelledError:
                raise
            except (UpstreamError, ValueError):
                continue
            rows = _team_rows(detail, team.team_id)
            if rows is None:
                continue
            source = LineupSourceMatch(
                match_id=match_id,
                start_time=datetime.fromtimestamp(
                    _number(detail.get("start_time")) or _number(summary.get("start_time")) or 0,
                    UTC,
                ),
            )
            coverage = LineupCoverage(
                completed_records_considered=considered,
                details_requested=requested,
                parsed_usable=1,
            )
            observed = {_positive_int(row.get("account_id")) for row in rows}
            if observed != current_members:
                return LatestObservedLineupResponse(
                    team=team,
                    source_match=source,
                    coverage=coverage,
                    error=_detail(
                        "lineup_mismatch",
                        "The newest usable observed lineup differs from explicit current members; "
                        "this may indicate a stand-in or roster change.",
                    ),
                )
            names = {
                account_id: str(item["name"])
                for item in professionals
                if (account_id := _positive_int(item.get("account_id"))) and item.get("name")
            }
            players, warnings = infer_positions(rows, names)
            return LatestObservedLineupResponse(
                team=team,
                source_match=source,
                coverage=coverage,
                players=players,
                warnings=warnings,
            )
        return LatestObservedLineupResponse(
            team=team,
            coverage=LineupCoverage(
                completed_records_considered=len(completed),
                details_requested=requested,
                parsed_usable=0,
            ),
            error=_detail(
                "lineup_unavailable",
                "None of the newest five completed records establishes a usable parsed "
                "five-player lineup.",
            ),
        )


def infer_positions(
    rows: list[dict[str, Any]], professional_names: dict[int, str]
) -> tuple[list[LineupPlayer], list[DataWarning]]:
    """Infer positions only from clean lane and ten-minute farm evidence."""
    evidence: list[dict[str, Any]] = []
    for row in rows:
        account_id = _positive_int(row.get("account_id"))
        assert account_id is not None
        lane_id = _positive_int(row.get("lane_role") or row.get("lane"))
        evidence.append(
            {
                "account_id": account_id,
                "pro_name": professional_names.get(account_id),
                "lane": LANES.get(lane_id or -1),
                "last_hits_at_10": _sample_at_10(row),
                "position": None,
            }
        )
    lanes = {name: [item for item in evidence if item["lane"] == name] for name in LANES.values()}
    clean = (
        len(lanes["safelane"]) == 2 and len(lanes["midlane"]) == 1 and len(lanes["offlane"]) == 2
    )
    if clean:
        lanes["midlane"][0]["position"] = 2
        _rank_lane(lanes["safelane"], high=1, low=5)
        _rank_lane(lanes["offlane"], high=3, low=4)
    players = [
        LineupPlayer(
            account_id=item["account_id"],
            pro_name=item["pro_name"],
            position=item["position"],
            lane=item["lane"],
            last_hits_at_10=item["last_hits_at_10"],
            inference_status="inferred" if item["position"] is not None else "ambiguous",
        )
        for item in evidence
    ]
    if all(item.position is not None for item in players):
        players.sort(key=lambda item: item.position or 99)
        return players, []
    players.sort(key=lambda item: (item.position is None, item.position or 99, item.account_id))
    return players, [
        DataWarning(
            code="position_ambiguous",
            message=(
                "One or more positions lack a clean 2-1-2 lane distribution with distinct "
                "ten-minute side-lane farm evidence."
            ),
        )
    ]


def _rank_lane(players: list[dict[str, Any]], *, high: int, low: int) -> None:
    values = [item["last_hits_at_10"] for item in players]
    if None in values or len(set(values)) != 2:
        return
    ordered = sorted(players, key=lambda item: item["last_hits_at_10"], reverse=True)
    ordered[0]["position"], ordered[1]["position"] = high, low


def _sample_at_10(row: dict[str, Any]) -> int | None:
    values = row.get("lh_t")
    if not isinstance(values, list):
        return None
    times = row.get("times")
    if isinstance(times, list) and len(times) == len(values):
        valid = [
            number
            for timestamp, value in zip(times, values, strict=True)
            if (_number(timestamp) is not None and float(timestamp) <= 600)
            and (number := _nonnegative_int(value)) is not None
        ]
        return valid[-1] if valid else None
    return _nonnegative_int(values[min(10, len(values) - 1)]) if values else None


def _team_rows(detail: dict[str, Any], team_id: int) -> list[dict[str, Any]] | None:
    if _positive_int(detail.get("version")) is None:
        return None
    radiant_id = _positive_int(detail.get("radiant_team_id"))
    dire_id = _positive_int(detail.get("dire_team_id"))
    if (radiant_id == team_id) == (dire_id == team_id):
        return None
    radiant = radiant_id == team_id
    rows = (
        [item for item in detail.get("players", []) if isinstance(item, dict)]
        if isinstance(detail.get("players"), list)
        else []
    )
    selected = [item for item in rows if _is_radiant(item) == radiant]
    ids = [_positive_int(item.get("account_id")) for item in selected]
    return selected if len(selected) == 5 and None not in ids and len(set(ids)) == 5 else None


def _current_members(records: list[dict[str, Any]]) -> set[int] | None:
    ids = [
        account_id
        for item in records
        if item.get("is_current_team_member") is True
        and (account_id := _positive_int(item.get("account_id"))) is not None
    ]
    return set(ids) if len(ids) == 5 and len(set(ids)) == 5 else None


def _completed_history(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[int, dict[str, Any]] = {}
    for item in records:
        match_id = _positive_int(item.get("match_id"))
        if match_id and _number(item.get("start_time")) is not None:
            unique[match_id] = item
    return sorted(
        unique.values(),
        key=lambda item: (_number(item.get("start_time")) or 0, int(item["match_id"])),
        reverse=True,
    )


def _team_reference(record: dict[str, Any], fallback_id: int | None = None) -> RosterTeamReference:
    team_id = _positive_int(record.get("team_id")) or fallback_id
    if team_id is None:
        raise ValueError("team record is missing a positive team ID")
    return RosterTeamReference(team_id=team_id, name=str(record.get("name") or team_id))


def _team_candidate(record: dict[str, Any]) -> RosterTeamCandidate:
    reference = _team_reference(record)
    return RosterTeamCandidate(
        **reference.model_dump(), tag=str(record["tag"]) if record.get("tag") else None
    )


def _detail(code: str, message: str) -> ToolErrorDetail:
    return ToolErrorDetail(code=code, message=message, tool=TOOL_NAME)


def _error(code: str, message: str) -> LatestObservedLineupResponse:
    return LatestObservedLineupResponse(error=_detail(code, message))


def _is_radiant(row: dict[str, Any]) -> bool | None:
    if isinstance(row.get("isRadiant"), bool):
        return bool(row["isRadiant"])
    slot = _nonnegative_int(row.get("player_slot"))
    return slot < 128 if slot is not None else None


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _number(value: object) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )
