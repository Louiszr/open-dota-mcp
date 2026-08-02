"""Transactional SQLite response store and management API."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from open_dota_mcp.cache.identity import API_CONTRACT, CacheIdentity
from open_dota_mcp.cache.policy import Freshness

SCHEMA_VERSION = 1
DATABASE_NAME = "responses.sqlite3"
MIN_DATABASE_BYTES = 65_536
SUPPORTED_OPERATIONS = frozenset(
    {
        "get_match",
        "get_heroes",
        "get_patches",
        "get_leagues",
        "get_league_matches",
        "get_teams_page",
        "get_team",
        "get_team_matches",
        "get_pro_players",
    }
)


class CacheUnavailableError(RuntimeError):
    """Raised when local cache state cannot be safely used."""


class _CapacityError(RuntimeError):
    """Internal rollback signal for a response that cannot fit."""


@dataclass(frozen=True, slots=True)
class CacheInfo:
    """Bounded aggregate cache information."""

    entry_count: int
    stored_payload_bytes: int
    allocated_database_bytes: int
    configured_max_bytes: int
    hits: int
    misses: int
    writes: int
    expirations: int
    evictions: int
    bypasses: int


@dataclass(frozen=True, slots=True)
class EntrySummary:
    """Secret-free response entry metadata."""

    kind: Literal["response"]
    safe_description: str
    operation: str
    category: Literal["short", "long"]
    created_at: str
    expires_at: str
    stored_size: int
    last_used_at: str
    reuse_count: int


@dataclass(frozen=True, slots=True)
class EntryPage:
    """A bounded seek-paginated entry page."""

    entries: tuple[EntrySummary, ...]
    returned_count: int
    limit: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ClearResult:
    """Counts removed by a confirmed clear operation."""

    removed_entries: int
    removed_payload_bytes: int
    generation: int


@dataclass(frozen=True, slots=True)
class PopulationLease:
    """Generation-bound ownership of one population attempt."""

    attempt_id: str
    generation: int
    owned: bool


@dataclass(frozen=True, slots=True)
class PopulationFailure:
    """Sanitized terminal failure shared with attached waiters."""

    code: str
    message: str
    status_code: int | None
    retry_exhausted: bool
    retryable_later: bool
    reason: str | None = None
    retry_after_seconds: float | None = None


class CacheStore:
    """Owner-only bounded SQLite cache for complete upstream JSON responses."""

    def __init__(
        self,
        cache_dir: Path,
        max_bytes: int = 1_073_741_824,
        *,
        clock: Callable[[], float] = time.time,
        busy_timeout_seconds: float = 2.0,
    ) -> None:
        """Initialize and validate the persistent store.

        Args:
            cache_dir: Owner-only directory containing the database.
            max_bytes: Maximum retained main-database allocation.
            clock: Injectable UTC epoch clock.
            busy_timeout_seconds: Finite SQLite lock wait.
        """
        if max_bytes <= 0:
            raise ValueError("cache max bytes must be positive")
        if max_bytes < MIN_DATABASE_BYTES:
            raise ValueError("cache_max_bytes is too small for initialized storage")
        self.cache_dir = Path(cache_dir).expanduser().absolute()
        self.path = self.cache_dir / DATABASE_NAME
        self.max_bytes = max_bytes
        self._clock = clock
        self._timeout = busy_timeout_seconds
        self._owner_id = uuid.uuid4().hex
        self._prepare_filesystem()
        self._bootstrap()

    def lookup(self, identity: CacheIdentity) -> Any | None:
        """Return one verified unexpired payload and update exact usage counters."""
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, payload_digest, stored_size, expires_at, generation "
                "FROM response_entries WHERE key_digest = ?",
                (identity.digest,),
            ).fetchone()
            if row is None:
                self._counter(connection, "misses")
                connection.commit()
                return None
            payload, digest, stored_size, expires_at, generation = row
            current_generation = self._generation(connection)
            if expires_at <= now or generation != current_generation:
                connection.execute(
                    "DELETE FROM response_entries WHERE key_digest = ?", (identity.digest,)
                )
                self._counter(connection, "misses")
                if expires_at <= now:
                    self._counter(connection, "expirations")
                connection.commit()
                return None
            try:
                if len(payload) != stored_size or hashlib.sha256(payload).hexdigest() != digest:
                    raise ValueError
                decoded = json.loads(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                connection.execute(
                    "DELETE FROM response_entries WHERE key_digest = ?", (identity.digest,)
                )
                self._counter(connection, "misses")
                self._counter(connection, "bypasses")
                connection.commit()
                return None
            connection.execute(
                "UPDATE response_entries SET last_used_at = ?, reuse_count = reuse_count + 1 "
                "WHERE key_digest = ?",
                (now, identity.digest),
            )
            self._counter(connection, "hits")
            connection.commit()
            return decoded

    def store(
        self,
        identity: CacheIdentity,
        payload: Any,
        freshness: Freshness,
        *,
        generation: int | None = None,
        attempt_id: str | None = None,
    ) -> bool:
        """Atomically store complete JSON if capacity and generation permit."""
        try:
            return self._store_transaction(
                identity,
                payload,
                freshness,
                generation=generation,
                attempt_id=attempt_id,
            )
        except _CapacityError:
            self.record_bypass()
            return False

    def _store_transaction(
        self,
        identity: CacheIdentity,
        payload: Any,
        freshness: Freshness,
        *,
        generation: int | None = None,
        attempt_id: str | None = None,
    ) -> bool:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        json.loads(encoded)
        if len(encoded) >= self.max_bytes:
            self.record_bypass()
            return False
        now = self._clock()
        digest = hashlib.sha256(encoded).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_generation = self._generation(connection)
            if generation is not None and generation != current_generation:
                connection.rollback()
                return False
            if attempt_id is not None:
                lease = connection.execute(
                    "SELECT attempt_id, owner_id, generation, lease_expires_at "
                    "FROM active_populations "
                    "WHERE key_digest = ?",
                    (identity.digest,),
                ).fetchone()
                if (
                    lease is None
                    or (lease[0], lease[1], lease[2])
                    != (
                        attempt_id,
                        self._owner_id,
                        current_generation,
                    )
                    or lease[3] <= now
                ):
                    connection.rollback()
                    return False
            self._remove_expired(connection, now)
            self._preflight_capacity(connection, identity.digest, len(encoded))
            connection.execute(
                "INSERT OR REPLACE INTO response_entries "
                "(key_digest, api_contract, operation, safe_description, payload, "
                "payload_digest, stored_size, category, created_at, expires_at, last_used_at, "
                "reuse_count, generation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    identity.digest,
                    API_CONTRACT,
                    identity.operation,
                    identity.safe_description,
                    encoded,
                    digest,
                    len(encoded),
                    freshness.category,
                    now,
                    now + freshness.ttl_seconds,
                    now,
                    current_generation,
                ),
            )
            if attempt_id:
                connection.execute(
                    "DELETE FROM active_populations WHERE key_digest = ?", (identity.digest,)
                )
            self._counter(connection, "writes")
            self._enforce_capacity(connection, identity.digest)
            connection.commit()
            return True

    def acquire_population(
        self,
        identity: CacheIdentity,
        lease_seconds: float = 30.0,
        *,
        attached: PopulationLease | None = None,
    ) -> PopulationLease:
        """Join a live population or atomically acquire its finite lease."""
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            generation = self._generation(connection)
            if attached is not None:
                if attached.generation != generation:
                    raise CacheUnavailableError("Cache was cleared during population wait")
                outcome = connection.execute(
                    "SELECT 1 FROM population_outcomes WHERE attempt_id = ? AND retain_until > ?",
                    (attached.attempt_id, now),
                ).fetchone()
                if outcome:
                    connection.commit()
                    return PopulationLease(attached.attempt_id, generation, False)
            available = connection.execute(
                "SELECT 1 FROM response_entries WHERE key_digest = ? AND generation = ? "
                "AND expires_at > ?",
                (identity.digest, generation, now),
            ).fetchone()
            if available:
                connection.commit()
                return PopulationLease("", generation, False)
            row = connection.execute(
                "SELECT attempt_id, generation, lease_expires_at FROM active_populations "
                "WHERE key_digest = ?",
                (identity.digest,),
            ).fetchone()
            if row is not None and row[1] == generation and row[2] > now:
                connection.commit()
                return PopulationLease(row[0], generation, False)
            attempt_id = uuid.uuid4().hex
            connection.execute(
                "INSERT OR REPLACE INTO active_populations "
                "(key_digest, attempt_id, owner_id, generation, started_at, lease_expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (identity.digest, attempt_id, self._owner_id, generation, now, now + lease_seconds),
            )
            connection.commit()
            return PopulationLease(attempt_id, generation, True)

    def release_population(self, identity: CacheIdentity, lease: PopulationLease) -> None:
        """Release a still-owned population lease after cancellation or failure."""
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM active_populations WHERE key_digest = ? AND attempt_id = ? "
                "AND owner_id = ? AND generation = ?",
                (identity.digest, lease.attempt_id, self._owner_id, lease.generation),
            )

    def renew_population(
        self, identity: CacheIdentity, lease: PopulationLease, lease_seconds: float = 30.0
    ) -> bool:
        """Renew a still-owned lease without spanning upstream I/O."""
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE active_populations SET lease_expires_at = ? WHERE key_digest = ? "
                "AND attempt_id = ? AND owner_id = ? AND generation = ? "
                "AND lease_expires_at > ?",
                (
                    self._clock() + lease_seconds,
                    identity.digest,
                    lease.attempt_id,
                    self._owner_id,
                    lease.generation,
                    self._clock(),
                ),
            )
        return result.rowcount == 1

    def complete_failure(
        self,
        identity: CacheIdentity,
        lease: PopulationLease,
        *,
        code: str,
        message: str,
        status_code: int | None,
        retry_exhausted: bool,
        retryable_later: bool,
        reason: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Publish a bounded terminal failure for callers attached to an attempt."""
        now = self._clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            owned = connection.execute(
                "SELECT 1 FROM active_populations WHERE key_digest = ? AND attempt_id = ? "
                "AND owner_id = ? AND generation = ? AND lease_expires_at > ?",
                (
                    identity.digest,
                    lease.attempt_id,
                    self._owner_id,
                    lease.generation,
                    now,
                ),
            ).fetchone()
            if owned:
                connection.execute(
                    "INSERT OR REPLACE INTO population_outcomes "
                    "(attempt_id, key_digest, generation, error_code, message, status_code, "
                    "retry_exhausted, retryable_later, reason, retry_after_seconds, completed_at, "
                    "retain_until) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        lease.attempt_id,
                        identity.digest,
                        lease.generation,
                        code[:80],
                        message[:300],
                        status_code,
                        int(retry_exhausted),
                        int(retryable_later),
                        reason[:40] if reason else None,
                        retry_after_seconds,
                        now,
                        now + 30.0,
                    ),
                )
                connection.execute(
                    "DELETE FROM active_populations WHERE key_digest = ?", (identity.digest,)
                )
            connection.commit()

    def population_failure(self, attempt_id: str) -> PopulationFailure | None:
        """Return a still-retained terminal outcome for an attached waiter."""
        now = self._clock()
        with self._connect() as connection:
            connection.execute("DELETE FROM population_outcomes WHERE retain_until <= ?", (now,))
            row = connection.execute(
                "SELECT error_code, message, status_code, retry_exhausted, retryable_later, "
                "reason, retry_after_seconds "
                "FROM population_outcomes WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            return None
        return PopulationFailure(row[0], row[1], row[2], bool(row[3]), bool(row[4]), row[5], row[6])

    def info(self) -> CacheInfo:
        """Return aggregate counters and main-database capacity values."""
        with self._connect() as connection:
            count, stored = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(stored_size), 0) FROM response_entries"
            ).fetchone()
            counters = connection.execute(
                "SELECT hits, misses, writes, expirations, evictions, bypasses "
                "FROM usage_summary WHERE id = 1"
            ).fetchone()
            allocated = self._allocated(connection)
        return CacheInfo(count, stored, allocated, self.max_bytes, *counters)

    def entries(
        self,
        *,
        operation: str | None = None,
        category: Literal["short", "long"] | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> EntryPage:
        """Return a filtered metadata-only entry page using a stable seek cursor."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if category not in {None, "short", "long"}:
            raise ValueError("category must be short or long")
        if operation is not None and operation not in SUPPORTED_OPERATIONS:
            raise ValueError("operation is not a supported OpenDota cache operation")
        seek = self._resolve_cursor(cursor, operation, category) if cursor else None
        conditions: list[str] = []
        values: list[Any] = []
        if operation:
            conditions.append("operation = ?")
            values.append(operation)
        if category:
            conditions.append("category = ?")
            values.append(category)
        if seek:
            conditions.append("(last_used_at < ? OR (last_used_at = ? AND key_digest > ?))")
            values.extend((seek[0], seek[0], seek[1]))
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key_digest, safe_description, operation, category, created_at, expires_at, "
                f"stored_size, last_used_at, reuse_count FROM response_entries {where} "
                "ORDER BY last_used_at DESC, key_digest ASC LIMIT ?",
                (*values, limit + 1),
            ).fetchall()
        visible = rows[:limit]
        summaries = tuple(
            EntrySummary(
                "response",
                row[1],
                row[2],
                row[3],
                _iso(row[4]),
                _iso(row[5]),
                row[6],
                _iso(row[7]),
                row[8],
            )
            for row in visible
        )
        next_cursor = None
        if len(rows) > limit and visible:
            next_cursor = self._create_cursor(visible[-1][7], visible[-1][0], operation, category)
        return EntryPage(summaries, len(summaries), limit, next_cursor)

    def clear(self) -> ClearResult:
        """Atomically clear response/coordination state and advance generation."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count, stored = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(stored_size), 0) FROM response_entries"
            ).fetchone()
            generation = self._generation(connection) + 1
            connection.execute("DELETE FROM response_entries")
            connection.execute("DELETE FROM active_populations")
            connection.execute("DELETE FROM population_outcomes")
            connection.execute("DELETE FROM entry_cursors")
            connection.execute(
                "UPDATE cache_control SET generation = ? WHERE id = 1", (generation,)
            )
            connection.execute("DELETE FROM usage_summary")
            connection.execute("INSERT INTO usage_summary (id) VALUES (1)")
            connection.commit()
        return ClearResult(count, stored, generation)

    def record_bypass(self) -> None:
        """Increment the bypass counter when the writable store remains available."""
        try:
            with self._connect() as connection:
                self._counter(connection, "bypasses")
        except (OSError, sqlite3.Error):
            pass

    def _prepare_filesystem(self) -> None:
        if self.cache_dir.is_symlink() or self.path.is_symlink():
            raise CacheUnavailableError("Cache paths must not be symbolic links")
        self.cache_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory_stat = self.cache_dir.stat()
        if directory_stat.st_uid != os.getuid():
            raise CacheUnavailableError("Cache directory must be owned by the current user")
        os.chmod(self.cache_dir, stat.S_IRWXU)
        if self.path.exists():
            path_stat = self.path.stat()
            if path_stat.st_uid != os.getuid():
                raise CacheUnavailableError("Cache database must be owned by the current user")
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self._timeout)
        connection.execute(f"PRAGMA busy_timeout = {int(self._timeout * 1000)}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count = {self.max_bytes // page_size}")
        connection.row_factory = sqlite3.Row
        return connection

    def _bootstrap(self) -> None:
        created = not self.path.exists()
        connection = sqlite3.connect(self.path, timeout=self._timeout)
        try:
            if created:
                connection.execute("PRAGMA auto_vacuum = FULL")
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS cache_control (
                    id INTEGER PRIMARY KEY CHECK (id = 1), generation INTEGER NOT NULL DEFAULT 0,
                    schema_version INTEGER NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS usage_summary (
                    id INTEGER PRIMARY KEY CHECK (id = 1), hits INTEGER NOT NULL DEFAULT 0,
                    misses INTEGER NOT NULL DEFAULT 0, writes INTEGER NOT NULL DEFAULT 0,
                    expirations INTEGER NOT NULL DEFAULT 0, evictions INTEGER NOT NULL DEFAULT 0,
                    bypasses INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS response_entries (
                    key_digest TEXT PRIMARY KEY,
                    api_contract TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    safe_description TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    payload_digest TEXT NOT NULL,
                    stored_size INTEGER NOT NULL CHECK (stored_size > 0), category TEXT NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL NOT NULL, last_used_at REAL NOT NULL,
                    reuse_count INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS response_expiry ON response_entries(expires_at);
                CREATE INDEX IF NOT EXISTS response_lru
                    ON response_entries(last_used_at, created_at, key_digest);
                CREATE INDEX IF NOT EXISTS response_filters
                    ON response_entries(operation, category, last_used_at, key_digest);
                CREATE TABLE IF NOT EXISTS active_populations (
                    key_digest TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    started_at REAL NOT NULL,
                    lease_expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS population_outcomes (
                    attempt_id TEXT PRIMARY KEY,
                    key_digest TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    error_code TEXT NOT NULL, message TEXT NOT NULL, status_code INTEGER,
                    retry_exhausted INTEGER NOT NULL, retryable_later INTEGER NOT NULL,
                    reason TEXT, retry_after_seconds REAL,
                    completed_at REAL NOT NULL, retain_until REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS outcome_expiry ON population_outcomes(retain_until);
                CREATE TABLE IF NOT EXISTS entry_cursors (
                    token_digest TEXT PRIMARY KEY, last_used_at REAL NOT NULL,
                    key_digest TEXT NOT NULL, operation TEXT, category TEXT,
                    created_at REAL NOT NULL, expires_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS cursor_expiry ON entry_cursors(expires_at);
                COMMIT;
                """
            )
            outcome_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(population_outcomes)")
            }
            if "reason" not in outcome_columns:
                connection.execute("ALTER TABLE population_outcomes ADD COLUMN reason TEXT")
            if "retry_after_seconds" not in outcome_columns:
                connection.execute(
                    "ALTER TABLE population_outcomes ADD COLUMN retry_after_seconds REAL"
                )
            connection.execute(
                "INSERT OR IGNORE INTO cache_control VALUES (1, 0, ?, ?)",
                (SCHEMA_VERSION, self._clock()),
            )
            connection.execute("INSERT OR IGNORE INTO usage_summary (id) VALUES (1)")
            version = connection.execute(
                "SELECT schema_version FROM cache_control WHERE id = 1"
            ).fetchone()[0]
            if version != SCHEMA_VERSION:
                raise CacheUnavailableError("Unsupported cache schema version")
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            if self.max_bytes < page_size * 8:
                raise ValueError("cache_max_bytes is too small for initialized storage")
            connection.execute(f"PRAGMA max_page_count = {self.max_bytes // page_size}")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
            if self._allocated(connection) > self.max_bytes:
                raise ValueError("cache_max_bytes is too small for initialized storage")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)

    @staticmethod
    def _counter(connection: sqlite3.Connection, name: str, amount: int = 1) -> None:
        if name not in {"hits", "misses", "writes", "expirations", "evictions", "bypasses"}:
            raise ValueError("unknown cache counter")
        connection.execute(f"UPDATE usage_summary SET {name} = {name} + ? WHERE id = 1", (amount,))

    @staticmethod
    def _generation(connection: sqlite3.Connection) -> int:
        return int(
            connection.execute("SELECT generation FROM cache_control WHERE id = 1").fetchone()[0]
        )

    def _remove_expired(self, connection: sqlite3.Connection, now: float) -> None:
        count = connection.execute(
            "SELECT COUNT(*) FROM response_entries WHERE expires_at <= ?", (now,)
        ).fetchone()[0]
        if count:
            connection.execute("DELETE FROM response_entries WHERE expires_at <= ?", (now,))
            self._counter(connection, "expirations", count)

    def _enforce_capacity(self, connection: sqlite3.Connection, protected: str) -> None:
        while self._allocated(connection) > self.max_bytes:
            candidate = connection.execute(
                "SELECT key_digest FROM response_entries WHERE key_digest != ? "
                "ORDER BY last_used_at ASC, created_at ASC, key_digest ASC LIMIT 1",
                (protected,),
            ).fetchone()
            if candidate is None:
                raise _CapacityError("cache response cannot fit configured capacity")
            connection.execute("DELETE FROM response_entries WHERE key_digest = ?", (candidate[0],))
            self._counter(connection, "evictions")

    def _preflight_capacity(
        self, connection: sqlite3.Connection, protected: str, incoming_size: int
    ) -> None:
        existing_size = connection.execute(
            "SELECT COALESCE(SUM(stored_size), 0) FROM response_entries WHERE key_digest != ?",
            (protected,),
        ).fetchone()[0]
        overhead = max(0, self._allocated(connection) - existing_size)
        while overhead + existing_size + incoming_size > self.max_bytes:
            candidate = connection.execute(
                "SELECT key_digest, stored_size FROM response_entries WHERE key_digest != ? "
                "ORDER BY last_used_at ASC, created_at ASC, key_digest ASC LIMIT 1",
                (protected,),
            ).fetchone()
            if candidate is None:
                raise _CapacityError("cache response cannot fit configured capacity")
            connection.execute("DELETE FROM response_entries WHERE key_digest = ?", (candidate[0],))
            existing_size -= candidate[1]
            self._counter(connection, "evictions")

    def _resolve_cursor(
        self,
        cursor: str,
        operation: str | None,
        category: str | None,
    ) -> tuple[float, str]:
        token_digest = hashlib.sha256(cursor.encode()).hexdigest()
        now = self._clock()
        with self._connect() as connection:
            connection.execute("DELETE FROM entry_cursors WHERE expires_at <= ?", (now,))
            row = connection.execute(
                "SELECT last_used_at, key_digest, operation, category FROM entry_cursors "
                "WHERE token_digest = ?",
                (token_digest,),
            ).fetchone()
            connection.execute("DELETE FROM entry_cursors WHERE token_digest = ?", (token_digest,))
        if row is None or row[2] != operation or row[3] != category:
            raise ValueError("invalid cursor")
        return float(row[0]), str(row[1])

    def _create_cursor(
        self,
        last_used_at: float,
        key_digest: str,
        operation: str | None,
        category: str | None,
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        with self._connect() as connection:
            connection.execute("DELETE FROM entry_cursors WHERE expires_at <= ?", (now,))
            connection.execute(
                "INSERT INTO entry_cursors VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    last_used_at,
                    key_digest,
                    operation,
                    category,
                    now,
                    now + 300.0,
                ),
            )
            connection.execute(
                "DELETE FROM entry_cursors WHERE token_digest IN "
                "(SELECT token_digest FROM entry_cursors ORDER BY created_at DESC "
                "LIMIT -1 OFFSET 1000)"
            )
        return token

    @staticmethod
    def _allocated(connection: sqlite3.Connection) -> int:
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        return int(page_count * page_size)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")
