from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastmcp import Client


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
