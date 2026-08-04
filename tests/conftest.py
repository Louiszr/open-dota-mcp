from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client

from open_dota_mcp.cache.store import CacheStore


@pytest.fixture
def fantasy_fixture() -> dict[str, Any]:
    """Load the explicit TI 2026 fantasy fixture document."""
    path = Path(__file__).parent / "fixtures" / "opendota" / "fantasy.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["professional_maps"]) == 30
    return payload


class MutableClock:
    """Deterministic mutable UTC wall clock."""

    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        """Advance the clock by an exact duration."""
        self.value += seconds


@pytest.fixture
def fixed_now() -> datetime:
    """Return a stable UTC instant for deterministic tests."""
    return datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
def clock(fixed_now: datetime) -> Callable[[], float]:
    """Return a monotonic clock tied to mutable test state."""
    state = {"value": fixed_now.timestamp()}

    def read() -> float:
        return state["value"]

    read.state = state  # type: ignore[attr-defined]
    return read


@pytest.fixture
def sleeper(clock: Callable[[], float]) -> Callable[[float], Awaitable[None]]:
    """Return a sleeper that advances the test clock without real delay."""

    async def sleep(delay: float) -> None:
        clock.state["value"] += delay  # type: ignore[attr-defined]

    return sleep


@pytest.fixture
def jitter() -> Callable[[float], float]:
    """Return deterministic zero jitter."""
    return lambda _upper: 0.0


@pytest.fixture
def wall_clock(fixed_now: datetime) -> MutableClock:
    """Return a mutable wall clock for expiry and lease tests."""
    return MutableClock(fixed_now.timestamp())


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Return a temporary owner-only cache directory path."""
    path = tmp_path / "cache"
    path.mkdir(mode=0o700)
    return path


@pytest.fixture
def cache_store(cache_dir: Path, wall_clock: MutableClock) -> CacheStore:
    """Return a deterministic temporary SQLite cache store."""
    return CacheStore(cache_dir, clock=wall_clock)


@pytest.fixture
def transport_factory() -> Callable[
    [Callable[[httpx.Request], httpx.Response]], httpx.MockTransport
]:
    """Build an offline HTTP transport from a request handler."""
    return httpx.MockTransport


@pytest.fixture
def mcp_client_factory() -> type[Client]:
    """Return the in-memory FastMCP client constructor."""
    return Client


@pytest.fixture
async def anyio_backend() -> AsyncIterator[str]:
    """Use asyncio for FastMCP-compatible asynchronous tests."""
    yield "asyncio"


def pytest_assertrepr_compare(op: str, left: Any, right: Any) -> list[str] | None:
    """Keep structured assertion output concise."""
    if op == "==" and isinstance(left, dict) and isinstance(right, dict):
        return ["structured dictionaries differ", f"left={left!r}", f"right={right!r}"]
    return None
