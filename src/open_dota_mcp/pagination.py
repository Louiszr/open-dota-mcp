"""Opaque rotating snapshot pagination for mutable upstream collections."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from open_dota_mcp.models.common import PageMetadata

T = TypeVar("T")


class PaginationError(ValueError):
    """A classified invalid or expired continuation request."""

    def __init__(self, code: str, message: str, *, restart_required: bool = False) -> None:
        """Create a pagination failure."""
        super().__init__(message)
        self.code = code
        self.restart_required = restart_required


@dataclass(slots=True)
class _Snapshot[T]:
    tool: str
    fingerprint: str
    items: tuple[T, ...]
    page_size: int
    offset: int
    created_at: float
    expires_at: float
    last_access: float
    token: str


class SnapshotRegistry:
    """Bounded process-local registry of immutable traversal snapshots."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 1800.0,
        capacity: int = 32,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        """Initialize traversal limits and injectable deterministic dependencies."""
        if ttl_seconds <= 0 or capacity <= 0:
            raise ValueError("Snapshot limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._snapshots: OrderedDict[str, _Snapshot[Any]] = OrderedDict()
        self._tokens: dict[str, str] = {}
        self._stale_tokens: set[str] = set()

    @staticmethod
    def fingerprint(query: dict[str, Any]) -> str:
        """Create a canonical query fingerprint independent of key ordering."""
        canonical = json.dumps(query, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def first_page(
        self,
        *,
        tool: str,
        query: dict[str, Any],
        items: list[T],
        page_size: int = 20,
    ) -> tuple[list[T], PageMetadata]:
        """Snapshot a result set and return its bounded first page."""
        self._validate_page_size(page_size)
        self._purge_expired()
        page = list(items[:page_size])
        if len(items) <= page_size:
            return page, PageMetadata(returned_count=len(page), page_size=page_size, terminal=True)
        self._evict_if_needed()
        now = self._clock()
        snapshot_id = secrets.token_hex(16)
        token = self._unique_token()
        snapshot = _Snapshot(
            tool=tool,
            fingerprint=self.fingerprint(query),
            items=tuple(items),
            page_size=page_size,
            offset=page_size,
            created_at=now,
            expires_at=now + self.ttl_seconds,
            last_access=now,
            token=token,
        )
        self._snapshots[snapshot_id] = snapshot
        self._tokens[token] = snapshot_id
        return page, self._metadata(page, snapshot, token=token)

    def next_page(
        self,
        token: str,
        *,
        tool: str,
        query: dict[str, Any] | None = None,
    ) -> tuple[list[Any], PageMetadata]:
        """Consume the current single-use token and rotate or terminate it."""
        self._purge_expired()
        snapshot_id = self._tokens.get(token)
        if snapshot_id is None:
            if token in self._stale_tokens:
                raise PaginationError(
                    "continuation_expired",
                    "Continuation state expired or was evicted; restart without a token",
                    restart_required=True,
                )
            raise PaginationError(
                "invalid_continuation", "Continuation token is invalid or replayed"
            )
        snapshot = self._snapshots[snapshot_id]
        if snapshot.tool != tool:
            raise PaginationError(
                "invalid_continuation", "Continuation token belongs to another tool"
            )
        if query is not None and self.fingerprint(query) != snapshot.fingerprint:
            raise PaginationError(
                "invalid_continuation", "Continuation inputs do not match the snapshot"
            )
        self._tokens.pop(token)
        snapshot.last_access = self._clock()
        self._snapshots.move_to_end(snapshot_id)
        start = snapshot.offset
        end = min(start + snapshot.page_size, len(snapshot.items))
        page = list(snapshot.items[start:end])
        snapshot.offset = end
        if end == len(snapshot.items):
            self._snapshots.pop(snapshot_id)
            return page, PageMetadata(
                returned_count=len(page), page_size=snapshot.page_size, terminal=True
            )
        next_token = self._unique_token()
        snapshot.token = next_token
        self._tokens[next_token] = snapshot_id
        return page, self._metadata(page, snapshot, token=next_token)

    def _metadata(self, page: list[Any], snapshot: _Snapshot[Any], *, token: str) -> PageMetadata:
        return PageMetadata(
            returned_count=len(page),
            page_size=snapshot.page_size,
            continuation_token=token,
            terminal=False,
            snapshot_expires_at=datetime.fromtimestamp(snapshot.expires_at, tz=UTC),
        )

    def _purge_expired(self) -> None:
        now = self._clock()
        expired = [key for key, value in self._snapshots.items() if value.expires_at <= now]
        for snapshot_id in expired:
            snapshot = self._snapshots.pop(snapshot_id)
            self._tokens.pop(snapshot.token, None)
            self._stale_tokens.add(snapshot.token)

    def _evict_if_needed(self) -> None:
        while len(self._snapshots) >= self.capacity:
            _snapshot_id, snapshot = self._snapshots.popitem(last=False)
            self._tokens.pop(snapshot.token, None)
            self._stale_tokens.add(snapshot.token)

    def _unique_token(self) -> str:
        token = self._token_factory()
        while token in self._tokens:
            token = self._token_factory()
        return token

    @staticmethod
    def _validate_page_size(page_size: int) -> None:
        if isinstance(page_size, bool) or not 1 <= page_size <= 100:
            raise PaginationError("invalid_page_size", "page_size must be between 1 and 100")
