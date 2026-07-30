from __future__ import annotations

import asyncio
import multiprocessing
from pathlib import Path

import httpx
import pytest

from open_dota_mcp.cache.identity import build_identity
from open_dota_mcp.cache.policy import Freshness
from open_dota_mcp.cache.store import CacheStore
from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.errors import UpstreamError


def _identity():
    return build_identity(source="https://api.opendota.com/api", operation="get_leagues")


def _success_worker(cache_dir: str, barrier, upstream_calls, results) -> None:
    barrier.wait()

    async def run() -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            with upstream_calls.get_lock():
                upstream_calls.value += 1
            return httpx.Response(200, json=[{"leagueid": 1}])

        settings = Settings(cache_dir=Path(cache_dir))
        async with OpenDotaClient(
            settings,
            transport=httpx.MockTransport(handler),
            cache_store=CacheStore(settings.cache_dir),
        ) as client:
            results.put(await client.get_leagues())

    asyncio.run(run())


def test_twenty_processes_share_one_successful_population(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    cache_dir = tmp_path / "cache"
    CacheStore(cache_dir)
    barrier = context.Barrier(20)
    upstream_calls = context.Value("i", 0)
    results = context.Queue()
    processes = [
        context.Process(
            target=_success_worker, args=(str(cache_dir), barrier, upstream_calls, results)
        )
        for _ in range(20)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    assert upstream_calls.value == 1
    assert [results.get(timeout=1) for _ in processes] == [[{"leagueid": 1}]] * 20


def test_shared_failure_later_attempt_crash_expiry_and_live_clear(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    owner = CacheStore(cache_dir, clock=lambda: 100.0)
    waiter = CacheStore(cache_dir, clock=lambda: 100.0)
    identity = _identity()
    lease = owner.acquire_population(identity, lease_seconds=5)
    attached = waiter.acquire_population(identity, lease_seconds=5)
    owner.complete_failure(
        identity,
        lease,
        code="upstream_unavailable",
        message="safe",
        status_code=503,
        retry_exhausted=True,
        retryable_later=True,
    )
    assert waiter.population_failure(attached.attempt_id).retry_exhausted  # type: ignore[union-attr]
    later = waiter.acquire_population(identity, lease_seconds=5)
    assert later.owned
    waiter.release_population(identity, later)

    crashed = owner.acquire_population(identity, lease_seconds=5)
    replacement = CacheStore(cache_dir, clock=lambda: 106.0).acquire_population(identity)
    assert crashed.owned and replacement.owned and crashed.attempt_id != replacement.attempt_id

    clear_result = waiter.clear()
    assert clear_result.generation == 1
    assert not owner.store(
        identity,
        [],
        Freshness("short", 900),
        generation=crashed.generation,
        attempt_id=crashed.attempt_id,
    )
    assert waiter.info().entry_count == 0 and waiter.info().hits == 0


@pytest.mark.asyncio
async def test_twenty_callers_share_identical_exhausted_failure_then_one_new_attempt(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    all_waiting = asyncio.Event()
    release_waiters = asyncio.Event()
    waiting = 0
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await all_waiting.wait()
        return httpx.Response(503)

    async def population_sleeper(_delay: float) -> None:
        nonlocal waiting
        waiting += 1
        if waiting == 19:
            all_waiting.set()
        await release_waiters.wait()

    settings = Settings(cache_dir=cache_dir, max_attempts=1)
    clients = [
        OpenDotaClient(
            settings,
            transport=httpx.MockTransport(handler),
            cache_store=CacheStore(cache_dir),
            population_sleeper=population_sleeper,
        )
        for _ in range(20)
    ]
    tasks = [asyncio.create_task(client.get_leagues()) for client in clients]
    await all_waiting.wait()
    release_waiters.set()
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    failures = [outcome for outcome in outcomes if isinstance(outcome, UpstreamError)]
    assert calls == 1
    assert len(failures) == 20
    assert all(
        error.retry_exhausted
        and error.code == "upstream_unavailable"
        and error.reason == "attempt_limit"
        for error in failures
    )
    assert {
        (str(error), error.status_code, error.retry_exhausted, error.retryable_later)
        for error in failures
    } == {("OpenDota availability recovery exhausted the attempt budget", 503, True, True)}
    with pytest.raises(UpstreamError):
        await clients[0].get_leagues()
    assert calls == 2
    await asyncio.gather(*(client.aclose() for client in clients))


@pytest.mark.asyncio
async def test_concurrent_population_has_one_shared_retry_sequence_and_cache_hit_bypass(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    attached = asyncio.Event()
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            await attached.wait()
            return httpx.Response(503)
        return httpx.Response(200, json=[{"leagueid": 1}])

    async def population_sleeper(_delay: float) -> None:
        attached.set()
        await asyncio.sleep(0)

    async def retry_sleeper(_delay: float) -> None:
        await asyncio.sleep(0)

    settings = Settings(cache_dir=cache_dir)
    clients = [
        OpenDotaClient(
            settings,
            transport=httpx.MockTransport(handler),
            cache_store=CacheStore(cache_dir),
            population_sleeper=population_sleeper,
            sleeper=retry_sleeper,
            jitter=lambda _upper: 0,
        )
        for _ in range(2)
    ]
    assert await asyncio.gather(*(client.get_leagues() for client in clients)) == [
        [{"leagueid": 1}],
        [{"leagueid": 1}],
    ]
    assert calls == 2
    assert await clients[1].get_leagues() == [{"leagueid": 1}]
    assert calls == 2
    await asyncio.gather(*(client.aclose() for client in clients))


@pytest.mark.asyncio
async def test_attached_waiter_cancellation_does_not_release_owner(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    owner = CacheStore(cache_dir)
    identity = _identity()
    lease = owner.acquire_population(identity)
    blocked = asyncio.Event()

    async def population_sleeper(_delay: float) -> None:
        blocked.set()
        await asyncio.Event().wait()

    client = OpenDotaClient(
        Settings(cache_dir=cache_dir),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[])),
        cache_store=CacheStore(cache_dir),
        population_sleeper=population_sleeper,
    )
    task = asyncio.create_task(client.get_leagues())
    await blocked.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert owner.renew_population(identity, lease)
    owner.release_population(identity, lease)
    await client.aclose()


@pytest.mark.asyncio
async def test_clear_with_twenty_active_callers_rejects_old_write_and_repopulates(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    all_waiting = asyncio.Event()
    release = asyncio.Event()
    waiting = 0
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            await all_waiting.wait()
            await release.wait()
        return httpx.Response(200, json=[])

    async def population_sleeper(_delay: float) -> None:
        nonlocal waiting
        waiting += 1
        if waiting == 19:
            all_waiting.set()
        await release.wait()

    settings = Settings(cache_dir=cache_dir)
    clients = [
        OpenDotaClient(
            settings,
            transport=httpx.MockTransport(handler),
            cache_store=CacheStore(cache_dir),
            population_sleeper=population_sleeper,
        )
        for _ in range(20)
    ]
    tasks = [asyncio.create_task(client.get_leagues()) for client in clients]
    await all_waiting.wait()
    cleared = CacheStore(cache_dir).clear()
    assert cleared.generation == 1
    immediate = CacheStore(cache_dir).info()
    assert (immediate.hits, immediate.misses, immediate.writes) == (0, 0, 0)
    release.set()
    assert await asyncio.gather(*tasks) == [[]] * 20
    cleared_info = CacheStore(cache_dir).info()
    assert cleared_info.entry_count == 0
    assert await clients[0].get_leagues() == []
    assert CacheStore(cache_dir).info().entry_count == 1
    await asyncio.gather(*(client.aclose() for client in clients))
