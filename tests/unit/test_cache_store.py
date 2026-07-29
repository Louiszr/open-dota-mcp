from __future__ import annotations

import multiprocessing
import os
import sqlite3
from pathlib import Path

import pytest

from open_dota_mcp.cache.identity import build_identity
from open_dota_mcp.cache.policy import Freshness
from open_dota_mcp.cache.store import CacheStore


def _interrupted_writer(database: str) -> None:
    connection = sqlite3.connect(database)
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        "INSERT INTO response_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "a" * 64,
            "opendota-public-api-v1",
            "get_leagues",
            "get_leagues()",
            b"[]",
            "b" * 64,
            2,
            "short",
            1.0,
            901.0,
            1.0,
            0,
            0,
        ),
    )
    os._exit(0)


def test_store_fixed_expiry_integrity_counters_entries_and_clear(tmp_path) -> None:
    state = {"now": 1000.0}
    store = CacheStore(tmp_path / "cache", clock=lambda: state["now"])
    identity = build_identity(
        source="https://api.opendota.com/api",
        operation="get_match",
        path_inputs={"match_id": 123},
    )
    assert store.lookup(identity) is None
    assert store.store(identity, {"match_id": 123}, Freshness("short", 900))
    assert store.lookup(identity) == {"match_id": 123}
    page = store.entries(limit=1)
    assert page.returned_count == 1
    assert page.entries[0].safe_description == "get_match(match_id=123)"
    state["now"] = 1900.0
    assert store.lookup(identity) is None
    info = store.info()
    assert (info.hits, info.misses, info.writes, info.expirations) == (1, 2, 1, 1)
    result = store.clear()
    assert result.generation == 1
    assert store.info().hits == 0
    assert os.stat(store.cache_dir).st_mode & 0o777 == 0o700
    assert os.stat(store.path).st_mode & 0o777 == 0o600


def test_corrupt_payload_is_never_returned(tmp_path) -> None:
    store = CacheStore(tmp_path / "cache")
    identity = build_identity(source="https://api.opendota.com/api", operation="get_leagues")
    assert store.store(identity, [], Freshness("short", 900))
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE response_entries SET payload = ? WHERE key_digest = ?",
            (b"not-json", identity.digest),
        )
    assert store.lookup(identity) is None


def test_schema_bootstrap_is_bounded_transactional_and_versioned(tmp_path: Path) -> None:
    store = CacheStore(tmp_path / "cache", max_bytes=131_072, busy_timeout_seconds=0.125)
    with sqlite3.connect(store.path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "cache_control",
            "response_entries",
            "usage_summary",
            "active_populations",
            "population_outcomes",
            "entry_cursors",
        } <= tables
        assert connection.execute("PRAGMA auto_vacuum").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    connection = store._connect()
    try:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 125
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        assert connection.execute("PRAGMA max_page_count").fetchone()[0] <= 131_072 // page_size
    finally:
        connection.close()


def test_undersized_initialization_is_atomic(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    with pytest.raises(ValueError, match="too small"):
        CacheStore(cache_dir, max_bytes=32_768)
    assert not cache_dir.exists()


def test_terminated_writer_leaves_no_partial_entry(tmp_path: Path) -> None:
    store = CacheStore(tmp_path / "cache")
    process = multiprocessing.get_context("spawn").Process(
        target=_interrupted_writer, args=(str(store.path),)
    )
    process.start()
    process.join(10)
    assert process.exitcode == 0
    assert CacheStore(store.cache_dir).info().entry_count == 0


def test_fixed_expiry_never_slides_and_handles_clock_movement(tmp_path: Path) -> None:
    now = {"value": 1000.0}
    store = CacheStore(tmp_path / "cache", clock=lambda: now["value"])
    identity = build_identity(source="https://api.opendota.com/api", operation="get_leagues")
    assert store.store(identity, [{"id": 1}], Freshness("short", 900))
    with sqlite3.connect(store.path) as connection:
        created, expires = connection.execute(
            "SELECT created_at, expires_at FROM response_entries"
        ).fetchone()
    now["value"] = 1500.0
    assert store.lookup(identity) == [{"id": 1}]
    now["value"] = 900.0
    assert store.lookup(identity) == [{"id": 1}]
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT created_at, expires_at FROM response_entries"
        ).fetchone() == (created, expires)
    now["value"] = expires
    assert store.lookup(identity) is None
    assert store.info().expirations == 1


def test_population_renewal_failure_outcome_and_generation_safe_clear(tmp_path: Path) -> None:
    now = {"value": 1000.0}
    owner = CacheStore(tmp_path / "cache", clock=lambda: now["value"])
    waiter = CacheStore(tmp_path / "cache", clock=lambda: now["value"])
    identity = build_identity(source="https://api.opendota.com/api", operation="get_leagues")
    lease = owner.acquire_population(identity, lease_seconds=5)
    attached = waiter.acquire_population(identity, lease_seconds=5)
    assert lease.owned and not attached.owned and lease.attempt_id == attached.attempt_id
    now["value"] = 1004.0
    assert owner.renew_population(identity, lease, lease_seconds=5)
    now["value"] = 1006.0
    assert not waiter.acquire_population(identity, lease_seconds=5).owned
    owner.complete_failure(
        identity,
        lease,
        code="upstream_unavailable",
        message="safe failure",
        status_code=503,
        retry_exhausted=True,
        retryable_later=True,
    )
    outcome = waiter.population_failure(attached.attempt_id)
    assert outcome is not None and outcome.retry_exhausted
    new_lease = owner.acquire_population(identity)
    result = waiter.clear()
    assert result.generation == 1
    assert not owner.store(
        identity,
        [],
        Freshness("short", 900),
        generation=new_lease.generation,
        attempt_id=new_lease.attempt_id,
    )


def test_expired_owner_cannot_renew_store_or_publish_failure(tmp_path: Path) -> None:
    now = {"value": 1000.0}
    store = CacheStore(tmp_path / "cache", clock=lambda: now["value"])
    identity = build_identity(source="https://api.opendota.com/api", operation="get_leagues")
    lease = store.acquire_population(identity, lease_seconds=1)
    now["value"] = 1001.0
    assert not store.renew_population(identity, lease)
    assert not store.store(
        identity,
        [],
        Freshness("short", 900),
        generation=lease.generation,
        attempt_id=lease.attempt_id,
    )
    store.complete_failure(
        identity,
        lease,
        code="expired",
        message="must not publish",
        status_code=None,
        retry_exhausted=True,
        retryable_later=True,
    )
    assert store.population_failure(lease.attempt_id) is None


def test_capacity_oversize_bypass_and_lru_eviction(tmp_path: Path) -> None:
    now = {"value": 1000.0}
    store = CacheStore(tmp_path / "cache", max_bytes=131_072, clock=lambda: now["value"])
    identities = [
        build_identity(
            source="https://api.opendota.com/api",
            operation="get_teams_page",
            query_inputs={"page": page},
        )
        for page in range(4)
    ]
    payload = [{"data": "x" * 20_000}]
    for identity in identities[:3]:
        assert store.store(identity, payload, Freshness("short", 900))
        now["value"] += 1
    assert store.store(identities[3], payload, Freshness("short", 900))
    assert store.info().allocated_database_bytes <= 131_072
    assert store.info().evictions == 1
    assert store.lookup(identities[0]) is None
    assert store.lookup(identities[3]) == payload
    before = store.info().entry_count
    assert not store.store(
        build_identity(source="https://api.opendota.com/api", operation="oversize"),
        {"data": "y" * 140_000},
        Freshness("short", 900),
    )
    assert store.info().entry_count == before
    retained = {entry.safe_description for entry in store.entries(limit=20).entries}
    assert not store.store(
        build_identity(source="https://api.opendota.com/api", operation="cannot-fit"),
        {"data": "z" * 100_000},
        Freshness("short", 900),
    )
    assert {entry.safe_description for entry in store.entries(limit=20).entries} == retained
    assert store.info().evictions == 1
    assert store.info().bypasses == 2
    journal = store.path.with_name(f"{store.path.name}-journal")
    journal.write_bytes(b"temporary" * 10_000)
    assert store.info().allocated_database_bytes == store.path.stat().st_size


def test_expired_entries_are_removed_before_capacity_and_population_is_protected(
    tmp_path: Path,
) -> None:
    now = {"value": 1000.0}
    store = CacheStore(tmp_path / "cache", max_bytes=131_072, clock=lambda: now["value"])
    expired = build_identity(source="https://api.opendota.com/api", operation="expired")
    active = build_identity(source="https://api.opendota.com/api", operation="active")
    store.store(expired, {"data": "x" * 20_000}, Freshness("short", 1))
    lease = store.acquire_population(active)
    now["value"] = 1002.0
    replacement = build_identity(source="https://api.opendota.com/api", operation="replacement")
    assert store.store(replacement, {"data": "y" * 20_000}, Freshness("short", 900))
    assert store.lookup(expired) is None
    assert store.renew_population(active, lease)
