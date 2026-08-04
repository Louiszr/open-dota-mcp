from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from open_dota_mcp.cache.store import CacheStore
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
        assert await client.get_player_matches(7, limit=20, offset=40) == []
        assert await client.get_team_players(2) == []
    assert any("/teams?page=4" in url for url in seen)
    assert any("/players/7/matches?limit=20&offset=40" in url for url in seen)


@pytest.mark.asyncio
async def test_all_operations_cache_before_shared_shape_validation(tmp_path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        path = request.url.path
        if path.endswith("/matches/1"):
            return httpx.Response(200, json={"match_id": 1})
        if path.endswith("/teams/2"):
            return httpx.Response(200, json={"team_id": 2})
        if path.endswith("/heroes"):
            return httpx.Response(200, json=[{"id": 1}])
        return httpx.Response(200, json=[])

    store = CacheStore(tmp_path / "cache")
    client = OpenDotaClient(
        Settings(cache_dir=tmp_path / "cache"),
        transport=httpx.MockTransport(handler),
        cache_store=store,
    )
    async with client:
        await client.get_match(1)
        await client.get_heroes()
        await client.get_patches()
        await client.get_leagues()
        await client.get_league_matches(3)
        await client.get_teams_page(4)
        await client.get_team(2)
        await client.get_team_matches(2)
        await client.get_pro_players()
        await client.get_player_matches(7, limit=20, offset=40)
        await client.get_team_players(2)
        first_calls = calls
        await client.get_match(1)
        await client.get_teams_page(4)
    assert calls == first_calls == 11
    entries = store.entries(limit=20).entries
    assert len(entries) == 11
    assert {
        entry.category for entry in entries if entry.operation in {"get_heroes", "get_patches"}
    } == {"long"}
    assert all(
        entry.category == "short"
        for entry in entries
        if entry.operation not in {"get_heroes", "get_patches"}
    )


@pytest.mark.asyncio
async def test_new_operation_argument_validation() -> None:
    async with OpenDotaClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[]))
    ) as client:
        with pytest.raises(ValueError):
            await client.get_player_matches(0)
        with pytest.raises(ValueError):
            await client.get_player_matches(1, limit=101)
        with pytest.raises(ValueError):
            await client.get_team_players(0)


@pytest.mark.asyncio
async def test_invalid_success_shape_is_not_cached(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"wrong": True})

    store = CacheStore(tmp_path / "cache")
    async with OpenDotaClient(
        Settings(cache_dir=tmp_path / "cache"),
        transport=httpx.MockTransport(handler),
        cache_store=store,
    ) as client:
        for _ in range(2):
            with pytest.raises(UpstreamError, match="top-level shape"):
                await client.get_leagues()
    assert calls == 2
    assert store.info().entry_count == 0


@pytest.mark.asyncio
async def test_async_lease_renews_through_commit(tmp_path) -> None:
    ready = asyncio.Event()
    loop = asyncio.get_running_loop()

    class TrackingStore(CacheStore):
        renewals = 0

        def renew_population(self, identity, lease, lease_seconds=30.0):
            self.renewals += 1
            loop.call_soon_threadsafe(ready.set)
            return super().renew_population(identity, lease, lease_seconds)

        def store(self, *args, **kwargs):
            assert self.renewals > 0
            return super().store(*args, **kwargs)

    store = TrackingStore(tmp_path / "cache")

    async def handler(_request: httpx.Request) -> httpx.Response:
        await ready.wait()
        return httpx.Response(200, json=[])

    async with OpenDotaClient(
        Settings(cache_dir=tmp_path / "cache"),
        transport=httpx.MockTransport(handler),
        cache_store=store,
        lease_renewal_interval=0,
    ) as client:
        assert await client.get_leagues() == []
    assert store.renewals >= 1 and store.info().entry_count == 1


@pytest.mark.asyncio
async def test_lease_renewal_failure_cannot_mask_fresh_success(tmp_path, caplog) -> None:
    attempted = asyncio.Event()
    loop = asyncio.get_running_loop()

    class FailingRenewalStore(CacheStore):
        attempted = False

        def renew_population(self, identity, lease, lease_seconds=30.0):
            self.attempted = True
            loop.call_soon_threadsafe(attempted.set)
            raise OSError("simulated renewal failure")

    store = FailingRenewalStore(tmp_path / "cache")

    async def handler(_request: httpx.Request) -> httpx.Response:
        await attempted.wait()
        return httpx.Response(200, json=[])

    async with OpenDotaClient(
        Settings(cache_dir=tmp_path / "cache"),
        transport=httpx.MockTransport(handler),
        cache_store=store,
        lease_renewal_interval=0,
    ) as client:
        assert await client.get_leagues() == []
    assert "renewal failed" in caplog.text.lower()


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
    assert delays == [2.0]


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
    assert delays == [2.4, 4.8, 9.6, 19.2, 38.4]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, "", "0", "-1", "nan", "inf", "invalid"])
async def test_unusable_retry_after_classes_use_safe_fallback(raw: str | None) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        headers = {"Retry-After": raw} if raw is not None else {}
        return httpx.Response(429 if attempts == 1 else 200, headers=headers, json=[])

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with OpenDotaClient(
        transport=httpx.MockTransport(handler), sleeper=sleep, jitter=lambda _upper: 0
    ) as client:
        assert await client.get_leagues() == []
    assert attempts == 2 and delays == [2]


@pytest.mark.asyncio
async def test_retry_after_seconds_date_and_repeated_short_guidance_never_undercut_base() -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    date_value = (now + timedelta(seconds=9)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    for header, expected in [("7", 7.0), (date_value, 9.0)]:
        attempts = 0
        delays: list[float] = []

        def handler(_request: httpx.Request, retry_after: str = header) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                429 if attempts == 1 else 200,
                headers={"Retry-After": retry_after},
                json=[],
            )

        async def sleep(delay: float, observed: list[float] = delays) -> None:
            observed.append(delay)

        async with OpenDotaClient(
            transport=httpx.MockTransport(handler),
            sleeper=sleep,
            jitter=lambda _upper: 0,
            wall_clock=lambda: now,
        ) as client:
            await client.get_leagues()
        assert delays == [expected]

    attempts = 0
    delays = []

    def repeated(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429 if attempts < 3 else 200, headers={"Retry-After": "1"}, json=[])

    async def repeated_sleep(delay: float) -> None:
        delays.append(delay)

    async with OpenDotaClient(
        transport=httpx.MockTransport(repeated),
        sleeper=repeated_sleep,
        jitter=lambda _upper: 0,
    ) as client:
        await client.get_leagues()
    assert delays == [2, 4]


@pytest.mark.asyncio
async def test_expired_http_date_uses_fallback_instead_of_immediate_retry() -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    expired = (now - timedelta(seconds=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429 if attempts == 1 else 200,
            headers={"Retry-After": expired},
            json=[],
        )

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with OpenDotaClient(
        transport=httpx.MockTransport(handler),
        sleeper=sleep,
        jitter=lambda _upper: 0,
        wall_clock=lambda: now,
    ) as client:
        await client.get_leagues()
    assert attempts == 2 and delays == [2]


@pytest.mark.asyncio
async def test_request_time_counts_toward_monotonic_elapsed_budget_before_sleep() -> None:
    now = {"value": 0.0}
    attempts = 0
    sleeps = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        now["value"] += 91
        return httpx.Response(503)

    async def sleep(_delay: float) -> None:
        nonlocal sleeps
        sleeps += 1

    async with OpenDotaClient(
        transport=httpx.MockTransport(handler),
        clock=lambda: now["value"],
        sleeper=sleep,
        jitter=lambda _upper: 0,
    ) as client:
        with pytest.raises(UpstreamError) as caught:
            await client.get_leagues()
    assert caught.value.reason == "elapsed_budget"
    assert attempts == 1 and sleeps == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("settings", "reason"),
    [
        (Settings(max_attempts=1), "attempt_limit"),
        (Settings(retry_delay_cap=1), "individual_delay"),
        (Settings(retry_delay_budget=1), "delay_budget"),
        (Settings(retry_elapsed_budget=1), "elapsed_budget"),
    ],
)
async def test_each_retry_budget_exhausts_without_an_extra_request(
    settings: Settings, reason: str
) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(handler),
        sleeper=lambda _delay: asyncio.sleep(0),
        jitter=lambda _upper: 0,
    ) as client:
        with pytest.raises(UpstreamError) as caught:
            await client.get_leagues()
    assert attempts == 1
    assert caught.value.reason == reason


@pytest.mark.asyncio
async def test_caller_deadline_refuses_sleep_and_cancellation_during_sleep_stops_attempts() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    async with OpenDotaClient(
        transport=httpx.MockTransport(handler),
        deadline=lambda: 1.0,
        clock=lambda: 0.0,
        jitter=lambda _upper: 0,
    ) as client:
        with pytest.raises(UpstreamError) as caught:
            await client.get_leagues()
    assert caught.value.reason == "deadline" and attempts == 1

    started = asyncio.Event()

    async def blocked_sleep(_delay: float) -> None:
        started.set()
        await asyncio.Event().wait()

    client = OpenDotaClient(
        transport=httpx.MockTransport(handler), sleeper=blocked_sleep, jitter=lambda _upper: 0
    )
    task = asyncio.create_task(client.get_leagues())
    await started.wait()
    calls_before_cancel = attempts
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await client.aclose()
    assert attempts == calls_before_cancel


@pytest.mark.asyncio
async def test_excessive_guidance_is_exposed_safely_without_raw_diagnostics(caplog) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            429, headers={"Retry-After": "99", "Authorization": "secret-header"}
        )
    )
    async with OpenDotaClient(
        Settings(api_key="secret-key"), transport=transport, jitter=lambda _upper: 0
    ) as client:
        with pytest.raises(UpstreamError) as caught:
            await client.get_leagues()
    assert caught.value.reason == "individual_delay"
    assert caught.value.retry_after_seconds == 99
    assert "secret-key" not in caplog.text and "secret-header" not in caplog.text
