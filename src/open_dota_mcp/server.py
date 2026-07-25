"""Exactly-three-tool FastMCP server construction and dependency wiring."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.errors import ToolErrorDetail
from open_dota_mcp.models.discovery import TeamResponse, TournamentResponse
from open_dota_mcp.models.drafts import DraftToolResponse
from open_dota_mcp.pagination import SnapshotRegistry
from open_dota_mcp.services.drafts import DraftService
from open_dota_mcp.services.matches import MatchDiscoveryService

logger = logging.getLogger(__name__)


def create_server(
    *,
    client: OpenDotaClient | None = None,
    registry: SnapshotRegistry | None = None,
    settings: Settings | None = None,
) -> FastMCP:
    """Build the standard server with injectable offline dependencies.

    Args:
        client: Optional preconfigured OpenDota client.
        registry: Optional process-local snapshot registry.
        settings: Optional environment-independent runtime settings.

    Returns:
        A FastMCP server exposing exactly three read-only tools.
    """
    runtime_settings = settings or Settings.from_env()
    owns_client = client is None
    runtime_client = client or OpenDotaClient(runtime_settings)
    runtime_registry = registry or SnapshotRegistry(
        ttl_seconds=runtime_settings.snapshot_ttl_seconds,
        capacity=runtime_settings.snapshot_capacity,
    )
    draft_service = DraftService(runtime_client)
    discovery_service = MatchDiscoveryService(runtime_client, runtime_registry)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        """Own and close the default HTTP client for the server lifetime."""
        try:
            yield {}
        finally:
            if owns_client:
                await runtime_client.aclose()

    server = FastMCP(
        "OpenDota Professional Analysis",
        instructions=(
            "Read-only professional Dota match discovery and ordered draft evidence. "
            "Use stable IDs after resolving ambiguous names."
        ),
        lifespan=lifespan,
    )

    @server.tool(
        name="get_pro_match_drafts",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        description=(
            "Retrieve compact ordered professional drafts for 1-10 match IDs. The slim default "
            "contains draft actions; include competition, result, draft_timing, and/or "
            "provenance. "
            "Duplicate IDs are silently collapsed and failures remain per-match."
        ),
    )
    async def get_pro_match_drafts(
        match_ids: list[int], include: list[str] | None = None
    ) -> DraftToolResponse:
        """Retrieve ordered professional draft evidence.

        Args:
            match_ids: One to ten positive IDs in caller order.
            include: Optional additive field groups.

        Returns:
            Sparse ordered draft outcomes or an actionable validation error.
        """
        try:
            response = await draft_service.get_drafts(match_ids, include=include)
            return DraftToolResponse(
                requested_match_ids=response.requested_match_ids,
                matches=response.matches,
            )
        except ValueError as exc:
            message = str(exc)
            code = "invalid_include" if "include" in message else "invalid_match_ids"
            return DraftToolResponse(
                error=ToolErrorDetail(
                    code=code,
                    message=message,
                    tool="get_pro_match_drafts",
                    valid_values=sorted({"competition", "result", "draft_timing", "provenance"})
                    if code == "invalid_include"
                    else None,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected draft tool failure (details masked from MCP response)")
            return DraftToolResponse(
                error=ToolErrorDetail(
                    code="upstream_unavailable",
                    message="Draft retrieval failed safely",
                    tool="get_pro_match_drafts",
                )
            )

    @server.tool(
        name="list_pro_tournament_matches",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        description=(
            "Resolve a professional league by ID or normalized name and return a slim newest-first "
            "page. First pages default to 20 and allow at most 100 records; follow the opaque "
            "token "
            "alone for an immutable traversal. Ambiguous names return bounded candidates."
        ),
    )
    async def list_pro_tournament_matches(
        league_id: int | None = None,
        tournament_name: str | None = None,
        page_size: int | None = None,
        continuation_token: str | None = None,
    ) -> TournamentResponse:
        """Discover professional tournament matches.

        Args:
            league_id: Positive stable league ID for a first page.
            tournament_name: Normalized exact or substring selector for a first page.
            page_size: First-page size from 1 through 100.
            continuation_token: Opaque single-use traversal token.

        Returns:
            Match page, bounded selection candidates, or a structured error.
        """
        return await discovery_service.list_tournament_matches(
            league_id=league_id,
            tournament_name=tournament_name,
            page_size=page_size,
            continuation_token=continuation_token,
        )

    @server.tool(
        name="list_pro_team_matches",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        description=(
            "Resolve a professional team by ID/name/tag and return a slim newest-first page. "
            "Optional inclusive UTC dates, radiant/dire side, and team-relative win/loss filters "
            "combine with "
            "AND semantics. Pages default to 20, max 100; continuation tokens preserve snapshots."
        ),
    )
    async def list_pro_team_matches(
        team_id: int | None = None,
        team_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        side: str | None = None,
        result: str | None = None,
        page_size: int | None = None,
        continuation_token: str | None = None,
    ) -> TeamResponse:
        """Discover filtered matches for one professional team.

        Args:
            team_id: Positive stable team ID for a first page.
            team_name: Normalized name or tag selector for a first page.
            start_date: Inclusive UTC date in YYYY-MM-DD form.
            end_date: Inclusive UTC date in YYYY-MM-DD form.
            side: Optional radiant or dire selection.
            result: Optional team-relative win or loss selection.
            page_size: First-page size from 1 through 100.
            continuation_token: Opaque single-use traversal token.

        Returns:
            Match page, bounded selection candidates, or a structured error.
        """
        return await discovery_service.list_team_matches(
            team_id=team_id,
            team_name=team_name,
            start_date=start_date,
            end_date=end_date,
            side=side,
            result=result,
            page_size=page_size,
            continuation_token=continuation_token,
        )

    return server


mcp = create_server()
