from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
import time
from pathlib import Path

from open_dota_mcp.cache.cli import run_cache_cli
from open_dota_mcp.cache.identity import build_identity
from open_dota_mcp.cache.policy import Freshness
from open_dota_mcp.cache.store import CacheStore
from open_dota_mcp.config import Settings


def test_cli_info_entries_and_confirmed_clear(tmp_path, capsys) -> None:
    settings = Settings(cache_dir=tmp_path / "cache")
    assert run_cache_cli(["info", "--json"], settings=settings) == 0
    assert json.loads(capsys.readouterr().out)["configured_max_bytes"] == 1_073_741_824
    assert run_cache_cli(["entries", "--limit", "501"], settings=settings) == 2
    assert run_cache_cli(["clear"], settings=settings) == 2
    capsys.readouterr()
    assert run_cache_cli(["clear", "--yes", "--json"], settings=settings) == 0
    assert json.loads(capsys.readouterr().out)["generation"] == 1


def test_cli_human_filters_seek_pages_counters_and_secret_exclusion(tmp_path: Path, capsys) -> None:
    settings = Settings(cache_dir=tmp_path / "cache")
    store = CacheStore(settings.cache_dir)
    for page, category in [(1, "short"), (2, "long"), (3, "short")]:
        identity = build_identity(
            source=settings.base_url,
            operation="get_teams_page",
            query_inputs={"page": page, "future_secret": "must-not-display"},
        )
        store.store(identity, [{"raw_secret": "never-output"}], Freshness(category, 900))
    assert run_cache_cli(["info"], settings=settings) == 0
    human = capsys.readouterr().out
    assert "entry_count: 3" in human and "stored_payload_bytes:" in human
    assert (
        run_cache_cli(
            ["entries", "--category", "short", "--limit", "1", "--json"], settings=settings
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert first["returned_count"] == 1 and first["next_cursor"]
    assert len(first["next_cursor"]) < 100
    assert not any(character in first["next_cursor"] for character in "{}[]:")
    tampered = f"{first['next_cursor']}x"
    assert run_cache_cli(["entries", "--cursor", tampered], settings=settings) == 2
    capsys.readouterr()
    assert (
        run_cache_cli(
            ["entries", "--category", "long", "--cursor", first["next_cursor"]],
            settings=settings,
        )
        == 2
    )
    capsys.readouterr()
    assert (
        run_cache_cli(
            ["entries", "--category", "short", "--limit", "1", "--json"], settings=settings
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert (
        run_cache_cli(
            [
                "entries",
                "--category",
                "short",
                "--limit",
                "1",
                "--cursor",
                first["next_cursor"],
                "--json",
            ],
            settings=settings,
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert second["returned_count"] == 1 and second["next_cursor"] is None
    rendered = json.dumps([first, second])
    assert "raw_secret" not in rendered and "must-not-display" not in rendered
    assert "key_digest" not in rendered and "payload" not in rendered
    assert run_cache_cli(["entries", "--cursor", "invalid"], settings=settings) == 2
    assert run_cache_cli(["entries", "--limit", "0"], settings=settings) == 2
    assert run_cache_cli(["entries", "--operation", "unknown"], settings=settings) == 2
    assert run_cache_cli(["entries", "--category", "medium"], settings=settings) == 2


def test_cli_operational_failure_is_status_one_and_secret_safe(tmp_path: Path, capsys) -> None:
    cache_dir = tmp_path / "corrupt"
    cache_dir.mkdir()
    (cache_dir / "responses.sqlite3").write_bytes(b"corrupt secret-looking bytes")
    status = run_cache_cli(["info", "--json"], settings=Settings(cache_dir=cache_dir))
    captured = capsys.readouterr()
    assert status == 1 and captured.out == ""
    assert "secret-looking" not in captured.err


def test_ten_thousand_entry_info_benchmark_and_output_bound(tmp_path: Path, capsys) -> None:
    settings = Settings(cache_dir=tmp_path / "cache")
    store = CacheStore(settings.cache_dir)
    payload = b"{}"
    payload_digest = hashlib.sha256(payload).hexdigest()
    rows = [
        (
            hashlib.sha256(str(index).encode()).hexdigest(),
            "opendota-public-api-v1",
            "benchmark",
            f"benchmark(page={index})",
            payload,
            payload_digest,
            len(payload),
            "short",
            1000.0,
            1900.0,
            1000.0,
            0,
            0,
        )
        for index in range(10_000)
    ]
    with sqlite3.connect(store.path) as connection:
        connection.executemany(
            "INSERT INTO response_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    run_cache_cli(["info", "--json"], settings=settings)
    capsys.readouterr()
    durations = []
    for _ in range(5):
        started = time.monotonic()
        assert run_cache_cli(["info", "--json"], settings=settings) == 0
        durations.append(time.monotonic() - started)
        assert json.loads(capsys.readouterr().out)["entry_count"] == 10_000
    assert statistics.median(durations) < 2.0
    page = store.entries(limit=500)
    assert page.returned_count == 500
