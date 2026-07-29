from __future__ import annotations

import asyncio
import multiprocessing
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

import open_dota_mcp.clients.opendota as opendota_module
from open_dota_mcp.cache.identity import build_identity
from open_dota_mcp.cache.policy import Freshness
from open_dota_mcp.cache.store import CacheStore, CacheUnavailableError
from open_dota_mcp.clients.opendota import OpenDotaClient
from open_dota_mcp.config import Settings
from open_dota_mcp.errors import UpstreamError
from open_dota_mcp.pagination import SnapshotRegistry


def _lifecycle_client_worker(cache_dir: str, upstream_calls, results) -> None:
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


@pytest.mark.asyncio
async def test_replacement_client_reuses_complete_upstream_payload(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[{"leagueid": 1, "future": True}])

    settings = Settings(cache_dir=tmp_path / "cache")
    transport = httpx.MockTransport(handler)
    async with OpenDotaClient(
        settings, transport=transport, cache_store=CacheStore(settings.cache_dir)
    ) as first:
        expected = await first.get_leagues()
    async with OpenDotaClient(
        settings, transport=transport, cache_store=CacheStore(settings.cache_dir)
    ) as second:
        assert await second.get_leagues() == expected
    assert calls == 1


def test_stopped_process_replacement_harness_and_restart_reuse(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    cache_dir = tmp_path / "cache"
    upstream_calls = context.Value("i", 0)
    results = context.Queue()
    for _ in range(2):
        process = context.Process(
            target=_lifecycle_client_worker,
            args=(str(cache_dir), upstream_calls, results),
        )
        process.start()
        process.join(10)
        assert process.exitcode == 0
        assert results.get(timeout=1) == [{"leagueid": 1}]
    assert upstream_calls.value == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "payload", "expected_ttl"),
    [
        ("get_heroes", [{"id": 1}], 86_400),
        ("get_patches", [], 86_400),
        ("get_match", {"match_id": 1, "version": 1}, 86_400),
        ("get_match", {"match_id": 1, "version": None}, 900),
        ("get_leagues", [], 900),
    ],
)
async def test_category_lifetimes_and_exact_refresh_boundary(
    tmp_path: Path, operation: str, payload: object, expected_ttl: int
) -> None:
    now = {"value": 1000.0}
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload)

    store = CacheStore(tmp_path / operation, clock=lambda: now["value"])
    client = OpenDotaClient(
        Settings(cache_dir=tmp_path / operation),
        transport=httpx.MockTransport(handler),
        cache_store=store,
    )
    method = getattr(client, operation)
    args = (1,) if operation == "get_match" else ()
    async with client:
        await method(*args)
        await method(*args)
        assert calls == 1
        with sqlite3.connect(store.path) as connection:
            created, expires = connection.execute(
                "SELECT created_at, expires_at FROM response_entries"
            ).fetchone()
        assert expires - created == expected_ttl
        now["value"] = expires
        await method(*args)
        assert calls == 2


@pytest.mark.asyncio
async def test_failed_refresh_never_serves_stale(tmp_path: Path) -> None:
    now = {"value": 1000.0}
    status = {"value": 200}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status["value"], json=[])

    store = CacheStore(tmp_path / "cache", clock=lambda: now["value"])
    settings = Settings(cache_dir=tmp_path / "cache", max_attempts=1)
    async with OpenDotaClient(
        settings, transport=httpx.MockTransport(handler), cache_store=store
    ) as client:
        assert await client.get_leagues() == []
        now["value"] = 1900.0
        status["value"] = 503
        with pytest.raises(UpstreamError):
            await client.get_leagues()
    assert store.info().entry_count == 0


def test_cache_faults_permissions_and_secret_safe_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    symlink = tmp_path / "link"
    target = tmp_path / "target"
    target.mkdir()
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(CacheUnavailableError, match="symbolic"):
        CacheStore(symlink)

    wrong_owner = tmp_path / "wrong-owner"
    wrong_owner.mkdir()
    monkeypatch.setattr("open_dota_mcp.cache.store.os.getuid", lambda: 999_999)
    with pytest.raises(CacheUnavailableError, match="current user"):
        CacheStore(wrong_owner)
    monkeypatch.undo()

    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "responses.sqlite3").write_bytes(b"not sqlite or a secret")
    with pytest.raises(sqlite3.DatabaseError) as caught:
        CacheStore(corrupt)
    assert "secret" not in str(caught.value)

    unsupported = CacheStore(tmp_path / "unsupported")
    with sqlite3.connect(unsupported.path) as connection:
        connection.execute("UPDATE cache_control SET schema_version = 999")
    with pytest.raises(CacheUnavailableError, match="Unsupported"):
        CacheStore(tmp_path / "unsupported")

    permissive = CacheStore(tmp_path / "permissive")
    permissive.cache_dir.chmod(0o777)
    permissive.path.chmod(0o666)
    repaired = CacheStore(permissive.cache_dir)
    assert repaired.cache_dir.stat().st_mode & 0o777 == 0o700
    assert repaired.path.stat().st_mode & 0o777 == 0o600
    assert repaired.cache_dir.stat().st_mode & 0o077 == 0
    assert repaired.path.stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
async def test_corrupt_cache_initialization_falls_back_to_fresh_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    original = opendota_module.CacheStore

    def unavailable(*_args, **_kwargs):
        raise sqlite3.DatabaseError("database is corrupt")

    monkeypatch.setattr(opendota_module, "CacheStore", unavailable)
    client = OpenDotaClient(Settings(cache_dir=tmp_path / "cache"))
    await client._http.aclose()
    client._http = httpx.AsyncClient(
        base_url=client.settings.base_url,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[])),
    )
    try:
        assert await client.get_leagues() == []
    finally:
        await client.aclose()
        monkeypatch.setattr(opendota_module, "CacheStore", original)
    assert "cache unavailable" in caplog.text.lower()


@pytest.mark.asyncio
async def test_lock_timeout_logs_and_returns_fresh_upstream(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = CacheStore(tmp_path / "locked", busy_timeout_seconds=0.01)
    lock = sqlite3.connect(store.path)
    lock.execute("BEGIN IMMEDIATE")
    try:
        async with OpenDotaClient(
            Settings(cache_dir=tmp_path / "locked"),
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[])),
            cache_store=store,
        ) as client:
            assert await client.get_leagues() == []
    finally:
        lock.rollback()
        lock.close()
    assert "cache bypassed" in caplog.text.lower()


@pytest.mark.asyncio
async def test_unwritable_cache_logs_and_returns_fresh_upstream(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = CacheStore(tmp_path / "unwritable")
    store.path.chmod(0o400)
    store.cache_dir.chmod(0o500)
    try:
        async with OpenDotaClient(
            Settings(cache_dir=store.cache_dir),
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[])),
            cache_store=store,
        ) as client:
            assert await client.get_leagues() == []
    finally:
        store.cache_dir.chmod(0o700)
        store.path.chmod(0o600)
    assert "cache" in caplog.text.lower()


def test_cache_clear_is_independent_of_process_local_pagination(tmp_path: Path) -> None:
    tokens = iter(["one", "two"])
    registry = SnapshotRegistry(token_factory=lambda: next(tokens))
    _, page = registry.first_page(tool="teams", query={"id": 1}, items=[1, 2, 3], page_size=1)
    store = CacheStore(tmp_path / "cache")
    identity = build_identity(source="https://api.opendota.com/api", operation="get_leagues")
    store.store(identity, [], Freshness("short", 900))
    store.clear()
    continued, metadata = registry.next_page(str(page.continuation_token), tool="teams")
    assert continued == [2] and metadata.terminal is False
    with sqlite3.connect(store.path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert not any("snapshot" in name or "pagination" in name for name in tables)


def test_second_nonprivileged_user_cannot_read_modify_inspect_or_clear(tmp_path: Path) -> None:
    sudo = shutil.which("sudo")
    if sudo is None:
        pytest.skip("host does not provide user-switching support")
    probe = subprocess.run([sudo, "-n", "-u", "nobody", "true"], capture_output=True, check=False)
    if probe.returncode != 0:
        pytest.skip("host does not permit passwordless nonprivileged-user tests")
    store = CacheStore(tmp_path / "cache")
    identity = build_identity(source="https://api.opendota.com/api", operation="get_leagues")
    assert store.store(identity, [], Freshness("short", 900))
    for flag, path in [
        ("-r", store.cache_dir),
        ("-w", store.cache_dir),
        ("-r", store.path),
        ("-w", store.path),
    ]:
        attempted = subprocess.run(
            [sudo, "-n", "-u", "nobody", "test", flag, str(path)],
            capture_output=True,
            check=False,
        )
        assert attempted.returncode != 0
    command = [
        sudo,
        "-n",
        "-u",
        "nobody",
        "env",
        f"OPENDOTA_CACHE_DIR={store.cache_dir}",
        sys.executable,
        "-m",
        "open_dota_mcp",
        "cache",
    ]
    for action in [["info", "--json"], ["clear", "--yes", "--json"]]:
        attempted = subprocess.run([*command, *action], capture_output=True, check=False)
        assert attempted.returncode != 0
    assert store.info().entry_count == 1
