from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastmcp import Client

from open_dota_mcp.cache.store import CacheStore
from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.errors import UpstreamError
from open_dota_mcp.server import create_server
from open_dota_mcp.services.drafts import DraftService


def match(match_id: int) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "start_time": 1784779200,
        "patch": 60,
        "leagueid": 10,
        "radiant_team_id": 1,
        "radiant_name": "Radiant Pro",
        "dire_team_id": 2,
        "dire_name": "Dire Pro",
        "radiant_win": True,
        "radiant_score": 31,
        "dire_score": 22,
        "duration": 2400,
        "league": {"name": "DreamLeague"},
        "picks_bans": [
            {"is_pick": False, "hero_id": 14, "team": 0, "order": 0},
            {"is_pick": True, "hero_id": 1, "team": 1, "order": 1},
        ],
        "players": [{"hero_id": 1, "player_slot": 128, "account_id": 42, "name": "Pro"}],
        "draft_timings": [{"order": 0}, {"order": 1}],
    }


class DraftClient:
    def __init__(self) -> None:
        self.calls = 0

    async def get_heroes(self) -> list[dict[str, Any]]:
        return [{"id": 1, "localized_name": "Anti-Mage"}, {"id": 14, "localized_name": "Pudge"}]

    async def get_patches(self) -> list[dict[str, Any]]:
        return [{"id": 0, "name": "6.70"}, {"id": 60, "name": "7.41"}]

    async def get_pro_players(self) -> list[dict[str, Any]]:
        return []

    async def get_match(self, match_id: int) -> dict[str, Any]:
        self.calls += 1
        if match_id == 404:
            raise UpstreamError("upstream_rejected", "not found", status_code=404)
        if match_id == 503:
            raise UpstreamError(
                "upstream_unavailable",
                "temporarily unavailable",
                retry_exhausted=True,
                retryable_later=True,
            )
        result = match(match_id)
        if match_id == 12:
            result["picks_bans"] = []
        return result

    async def get_league_matches(self, _league_id: int) -> list[dict[str, Any]]:
        return [{"match_id": value} for value in [1, 2, 12, 404, 503]]

    async def aclose(self) -> None:
        return None


async def call(client: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(create_server(client=client)) as session:  # type: ignore[arg-type]
        response = await session.call_tool("get_pro_match_drafts", arguments)
    return response.structured_content


@pytest.mark.asyncio
async def test_validation_deduplication_order_and_slim_default() -> None:
    fake = DraftClient()
    payload = await call(fake, {"match_ids": [2, 1, 2]})
    assert payload["requested_match_ids"] == [2, 1]
    assert [item["match_id"] for item in payload["matches"]] == [2, 1]
    draft = payload["matches"][0]["draft"]
    assert not {"competition", "result", "provenance"} & draft.keys()
    assert "status" not in draft and "warnings" not in draft

    before = fake.calls
    invalid = await call(fake, {"match_ids": [1], "include": ["raw"]})
    assert invalid["error"]["code"] == "invalid_include"
    assert fake.calls == before


@pytest.mark.asyncio
async def test_each_additive_group_and_all_groups() -> None:
    fake = DraftClient()
    for group in ["competition", "result", "draft_timing", "provenance"]:
        payload = await call(fake, {"match_ids": [1], "include": [group]})
        draft = payload["matches"][0]["draft"]
        if group == "draft_timing":
            assert "timing" in draft["draft_actions"][0]
        else:
            assert group in draft
    payload = await call(
        fake,
        {
            "match_ids": [1],
            "include": ["competition", "result", "draft_timing", "provenance"],
        },
    )
    assert payload["matches"][0]["draft"]["result"]["radiant_score"] == 31


@pytest.mark.asyncio
async def test_zero_patch_identifier_resolves_from_documented_constants_shape() -> None:
    fake = DraftClient()
    original_get_match = fake.get_match

    async def zero_patch_match(match_id: int) -> dict[str, Any]:
        result = await original_get_match(match_id)
        result["patch"] = 0
        return result

    fake.get_match = zero_patch_match  # type: ignore[method-assign]
    payload = await call(fake, {"match_ids": [1]})
    draft = payload["matches"][0]["draft"]
    assert draft["patch_id"] == 0
    assert draft["patch_version"] == "6.70"


@pytest.mark.asyncio
async def test_mixed_partial_and_failure_outcomes_remain_sparse() -> None:
    payload = await call(DraftClient(), {"match_ids": [1, 3, 12, 404, 503]})
    assert "draft" in payload["matches"][0]
    assert payload["matches"][1]["error"]["status"] == "not_professional"
    assert payload["matches"][2]["error"]["status"] == "not_parsed"
    assert payload["matches"][3]["error"]["status"] == "unavailable"
    assert payload["matches"][4]["error"]["retry_exhausted"] is True
    assert all("draft" not in item for item in payload["matches"][1:])


@pytest.mark.asyncio
async def test_partial_reference_data_warns_without_raw_or_null_error() -> None:
    fake = DraftClient()

    async def no_heroes() -> list[dict[str, Any]]:
        return []

    fake.get_heroes = no_heroes  # type: ignore[method-assign]
    payload = await call(fake, {"match_ids": [1]})
    draft = payload["matches"][0]["draft"]
    assert draft["completeness"] == "partial"
    assert "error" not in payload["matches"][0]
    assert all(action["hero"]["localized_name"] is None for action in draft["draft_actions"])


@pytest.mark.asyncio
async def test_cancellation_propagates_through_tool() -> None:
    fake = DraftClient()

    async def cancel(_match_id: int) -> dict[str, Any]:
        raise asyncio.CancelledError

    fake.get_match = cancel  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await DraftService(fake).get_drafts([1])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_tool_boundary_retry_after_recovery_exhaustion_and_rejection() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        path = request.url.path
        if path.endswith("/heroes"):
            return httpx.Response(200, json=[{"id": 1, "localized_name": "Anti-Mage"}])
        if path.endswith("/constants/patch") or path.endswith("/proPlayers"):
            return httpx.Response(200, json=[])
        if path.endswith("/leagues/10/matches"):
            return httpx.Response(200, json=[{"match_id": 1}])
        if path.endswith("/matches/1"):
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json=match(1))
        raise AssertionError(path)

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    upstream = OpenDotaClient(
        transport=httpx.MockTransport(handler), sleeper=sleeper, jitter=lambda _upper: 0
    )
    payload = await call(upstream, {"match_ids": [1]})
    await upstream.aclose()
    assert payload["matches"][0]["draft"]["match_id"] == 1
    assert attempts == 2 and delays == [2]

    for status, expected in [(503, "upstream_unavailable"), (403, "upstream_rejected")]:

        def failure_handler(request: httpx.Request, status_code: int = status) -> httpx.Response:
            path = request.url.path
            if (
                path.endswith("/heroes")
                or path.endswith("/constants/patch")
                or path.endswith("/proPlayers")
            ):
                return httpx.Response(200, json=[])
            return httpx.Response(status_code)

        upstream = OpenDotaClient(
            Settings(max_attempts=2),
            transport=httpx.MockTransport(failure_handler),
            sleeper=sleeper,
        )
        payload = await call(upstream, {"match_ids": [1]})
        await upstream.aclose()
        assert payload["matches"][0]["error"]["code"] == expected
        assert payload["matches"][0]["error"]["retry_exhausted"] is (status == 503)


@pytest.mark.asyncio
async def test_caller_deadline_cancels_pending_draft_work() -> None:
    fake = DraftClient()

    async def slow_match(_match_id: int) -> dict[str, Any]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    fake.get_match = slow_match  # type: ignore[method-assign]
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await DraftService(fake).get_drafts([1])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cached_and_fresh_draft_contracts_are_identical(tmp_path) -> None:
    calls = 0
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        path = request.url.path
        seen.append(path)
        if path.endswith("/heroes"):
            return httpx.Response(200, json=[{"id": 1, "localized_name": "Anti-Mage"}])
        if path.endswith("/constants/patch") or path.endswith("/proPlayers"):
            return httpx.Response(200, json=[])
        if path.endswith("/leagues/10/matches"):
            return httpx.Response(200, json=[{"match_id": 1}])
        return httpx.Response(200, json=match(1))

    settings = Settings(cache_dir=tmp_path / "cache")
    upstream = OpenDotaClient(
        settings,
        transport=httpx.MockTransport(handler),
        cache_store=CacheStore(settings.cache_dir),
    )
    fresh = await call(upstream, {"match_ids": [1], "include": ["result"]})
    first_calls = calls
    cached = await call(upstream, {"match_ids": [1], "include": ["result"]})
    await upstream.aclose()
    assert cached == fresh
    assert calls == first_calls, seen
