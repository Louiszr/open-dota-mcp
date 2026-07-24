from __future__ import annotations

import asyncio

import httpx
import pytest

from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.errors import UpstreamError


@pytest.mark.asyncio
async def test_every_documented_get_method_and_unknown_fields_are_permissive() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        path = request.url.path
        if path.endswith("/matches/1") or path.endswith("/teams/2"):
            return httpx.Response(200, json={"id": 1, "unknown": {"future": True}})
        if path.endswith("/heroes"):
            return httpx.Response(200, json=[{"id": 1, "localized_name": "Anti-Mage"}])
        return httpx.Response(200, json=[])

    async with OpenDotaClient(transport=httpx.MockTransport(handler)) as client:
        assert (await client.get_match(1))["unknown"]["future"] is True
        assert await client.get_heroes()
        assert await client.get_patches() == []
        assert await client.get_leagues() == []
        assert await client.get_league_matches(3) == []
        assert await client.get_teams_page(4) == []
        assert await client.get_team(2) == {"id": 1, "unknown": {"future": True}}
        assert await client.get_team_matches(2) == []
        assert await client.get_pro_players() == []
    assert any("/teams?page=4" in url for url in seen)


@pytest.mark.asyncio
async def test_no_authentication_by_default_and_optional_bearer_never_query() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    async with OpenDotaClient(transport=httpx.MockTransport(handler)) as client:
        await client.get_leagues()
    assert "Authorization" not in requests[-1].headers

    settings = Settings(api_key="secret")
    async with OpenDotaClient(settings, transport=httpx.MockTransport(handler)) as client:
        await client.get_leagues()
    assert requests[-1].headers["Authorization"] == "Bearer secret"
    assert "secret" not in str(requests[-1].url)


@pytest.mark.asyncio
async def test_malformed_top_level_shape_is_classified_and_secret_free() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"wrong": True}))
    async with OpenDotaClient(Settings(api_key="secret"), transport=transport) as client:
        with pytest.raises(UpstreamError) as caught:
            await client.get_leagues()
    assert caught.value.code == "upstream_contract"
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
async def test_retryable_status_recovers_with_bounded_delay(status: int) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(status, headers={"Retry-After": "1"} if status == 429 else {})
        return httpx.Response(200, json=[])

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async with OpenDotaClient(
        transport=httpx.MockTransport(handler), sleeper=sleeper, jitter=lambda _upper: 0
    ) as client:
        assert await client.get_leagues() == []
    assert attempts == 2
    assert delays == [1.0 if status == 429 else 0.25]


@pytest.mark.asyncio
async def test_invalid_retry_after_uses_exponential_jitter_fallback() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "invalid"})

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async with OpenDotaClient(
        transport=httpx.MockTransport(handler), sleeper=sleeper, jitter=lambda upper: upper
    ) as client:
        with pytest.raises(UpstreamError) as caught:
            await client.get_leagues()
    assert caught.value.code == "upstream_rate_limited"
    assert caught.value.retry_exhausted is True
    assert delays == [0.5, 1.0]


@pytest.mark.asyncio
async def test_connection_and_timeout_recovery() -> None:
    failures: list[type[httpx.RequestError]] = [httpx.ConnectError, httpx.ReadTimeout]
    for error_type in failures:
        attempts = 0

        def handler(
            request: httpx.Request,
            exception_type: type[httpx.RequestError] = error_type,
        ) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise exception_type("temporary", request=request)
            return httpx.Response(200, json=[])

        async def sleeper(_delay: float) -> None:
            return None

        async with OpenDotaClient(
            transport=httpx.MockTransport(handler), sleeper=sleeper
        ) as client:
            assert await client.get_leagues() == []


@pytest.mark.asyncio
async def test_delay_budget_refusal_and_nonretryable_failure() -> None:
    rate_limited = httpx.MockTransport(
        lambda _request: httpx.Response(429, headers={"Retry-After": "99"})
    )
    async with OpenDotaClient(Settings(retry_delay_budget=1), transport=rate_limited) as client:
        with pytest.raises(UpstreamError) as exhausted:
            await client.get_leagues()
    assert exhausted.value.retry_exhausted is True

    rejected = httpx.MockTransport(lambda _request: httpx.Response(403, text="secret-body"))
    async with OpenDotaClient(transport=rejected) as client:
        with pytest.raises(UpstreamError) as failure:
            await client.get_leagues()
    assert failure.value.code == "upstream_rejected"
    assert "secret-body" not in str(failure.value)


@pytest.mark.asyncio
async def test_cancellation_is_immediate() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    async with OpenDotaClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(asyncio.CancelledError):
            await client.get_leagues()
