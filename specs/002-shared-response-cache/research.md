# Phase 0 Research: Shared OpenDota Response Cache

## Existing OpenDota contract and cache boundary

**Decision**: Cache the complete successful JSON content returned by the existing nine typed GET
operations in `OpenDotaClient`, immediately after the established finite retry loop and before
object/list validation, domain transformation, filters, pagination slicing, or MCP field-group
selection. Do not add an endpoint or change authentication, retry, deadline, or cancellation
behavior.

**Rationale**: The official OpenDota [`odota/core` generated OpenAPI source](https://github.com/odota/core/blob/master/svc/api/spec.ts)
was rechecked on 2026-07-25. It still identifies the OpenAPI 3.0.3 server as
`https://api.opendota.com/api`, permits no-key access, and documents API-key use by query or
Bearer header. This repository continues to use only the Bearer form when configured. Feature
001 already verified the route-specific projections for `GET /matches/{match_id}`, `/heroes`,
`/constants/patch`, `/leagues`, `/leagues/{league_id}/matches`, `/teams?page=N`,
`/teams/{team_id}`, `/teams/{team_id}/matches`, and `/proPlayers`; feature 002 introduces no new
OpenDota interaction. Storing upstream content at the client boundary lets cache hits and fresh
responses pass through exactly the same validation and MCP shaping and keeps entries reusable
across compatible MCP releases.

The existing client retries only safe GET operations for 429, 408, selected 5xx statuses,
timeouts, and network failures. It honors valid `Retry-After` within the three-attempt,
10-second delay budget and propagates cancellation. One coordinated population owns that entire
policy; no error response or exhausted failure becomes a successful cache entry.

**Alternatives considered**: Caching final MCP models was rejected because optional `include`
groups and future compatible model changes would fragment or invalidate otherwise identical
upstream content. Caching inside each service was rejected because the same OpenDota operation is
used by multiple workflows. HTTP-library caching middleware was rejected because conditional
parsed-match classification, cross-process failure sharing, generation-safe clear, and counters
need domain-aware behavior.

## Persistent storage and process coordination

**Decision**: Use Python 3.13's standard `sqlite3` module with one database per local user. Use
short explicit transactions for complete BLOB reads/writes, population leases/outcomes, counters,
capacity cleanup, and full removal; execute blocking database work outside
the async event loop.

**Rationale**: Python's official [`sqlite3` documentation](https://docs.python.org/3.13/library/sqlite3.html)
describes an on-disk database requiring no separate server and provides transaction/lock timeout
control. SQLite's official [transaction documentation](https://sqlite.org/lang_transaction.html)
provides atomic visibility, and its rollback journal supplies crash-safe commit/rollback. That is
the smallest standard-library mechanism that simultaneously survives process/computer restarts
and coordinates unrelated local MCP processes. Explicit short write transactions ensure there is
one winner for a missing identity while avoiding locks during OpenDota I/O.

Initialize full auto-vacuum before tables, enforce the configured retained main-database bound
with `max_page_count`, and measure allocation using `page_count * page_size`, following SQLite's
official [PRAGMA documentation](https://sqlite.org/pragma.html). Use a finite busy timeout and
rollback-journal mode: local request volume is modest, reads copy a BLOB in a short transaction,
and the journal disappears after commit instead of remaining retained cache storage.

**Alternatives considered**: A process-local dictionary cannot survive either process or computer
restarts. Individual response files plus advisory locks require custom atomic metadata, orphan,
counter, and multi-process protocols. A new cache dependency adds supply/configuration surface but
does not eliminate the required generation and failure-sharing logic. Redis or another daemon is
outside the local zero-service scope. SQLite WAL improves writer/read concurrency, but its retained
WAL/checkpoint behavior complicates the exact single-file capacity boundary without a demonstrated
throughput need.

## Per-user location and access control

**Decision**: Default to the platform user-cache location—`~/Library/Caches/open-dota-mcp` on
macOS and `${XDG_CACHE_HOME:-~/.cache}/open-dota-mcp` on Linux—with a configurable
`OPENDOTA_CACHE_DIR`. Create the directory as `0700` and database as `0600`; reject symlinks,
wrong-owner paths, and access from another OS user. Do not encrypt public OpenDota payloads.

**Rationale**: Cache data is local application data rather than configuration, and the feature
scope is explicitly one operating-system user on one computer. Owner-only directory and file
permissions meet the stated confidentiality requirement without key management. A configurable
directory enables deterministic tests and machines with nonstandard storage, while ownership
validation prevents that setting from silently weakening the contract.

**Alternatives considered**: A repository-local cache would leak across checkouts and risk source
control inclusion. A system-wide cache violates the user boundary. Cache-specific encryption was
explicitly excluded and would add secret storage/rotation with no protected upstream private data.

## Canonical identity and secret exclusion

**Decision**: Hash canonical UTF-8 JSON containing an OpenDota API-contract namespace, normalized
source origin/base path, stable operation name, path inputs, and the complete structured query
mapping used to construct the GET URL. Treat every query parameter as content-altering by default.
Before canonicalization, remove only parameters on a centralized, explicit, code-reviewed
non-content-altering exclusion list; initially that list contains only `api_key` authentication
material. Sort mapping keys, encode scalar types unambiguously, retain order only where the
upstream contract makes order meaningful, and normalize explicitly unordered collections.
Exclude credentials and the current client's fixed headers by construction. Store only the digest
plus a bounded safe operation/selector description for inspection.

**Rationale**: The current upstream inputs are stable numeric IDs and the team catalog page. A
canonical identity maps reordered equivalent mappings to one row and keeps different base sources,
operations, IDs, pages, and newly added query inputs distinct. Default inclusion is fail-closed:
future feature work cannot accidentally reuse content across a new parameter merely because the
cache code was not updated. The worst case is a redundant cache entry, not an incorrect hit.
Including the OpenDota contract namespace—not the MCP package version—supports upgrade reuse.
`Authorization`, `api_key`, and `OPENDOTA_API_KEY` are authentication material under the selected
contract and are never identity inputs. The current client uses the Authorization header, so an API
key normally never enters the query mapping. MCP `include` groups also do not belong in the
identity because they shape content only after the upstream payload is obtained. Any future query
exclusion requires upstream-contract verification and a regression test proving that changing
only the excluded value deliberately preserves identity; exclusions are never inferred by name.

**Alternatives considered**: Hashing the raw complete URL risks query credentials and makes
harmless parameter ordering significant. Maintaining an allowlist of content-altering parameters
was rejected because every new parameter would be unsafe until separately classified. Hashing only
path text can collide across base sources or omit query shaping. Including the MCP version would
contradict the required compatible-upgrade reuse. Using a safe description as the primary key
risks collisions and expands sensitive inspection surface.

## Freshness classification and clock model

**Decision**: Default every cacheable operation to 900 seconds. Explicitly classify heroes and
patch constants as 86,400 seconds. Classify a match response as 86,400 seconds only when its
OpenDota `version` is a non-boolean positive integer confirming parsed data; otherwise use 900
seconds. Persist a wall-clock UTC `created_at` and fixed absolute `expires_at`; never update expiry
on a hit, restart, or clock adjustment.

**Rationale**: This is the safest direct encoding of FR-004 through FR-008 and makes long-lived
additions a small reviewable table. OpenDota's official
[`MatchResponse`](https://github.com/odota/core/blob/master/svc/api/responses/MatchResponse.ts)
includes the parse version, whereas missing/null/malformed values do not confirm parsing. A fixed
UTC expiry survives computer restart. Comparing `now < expires_at` rejects equality and forward
clock jumps; backward movement does not rewrite or extend the stored absolute timestamp.

**Alternatives considered**: Inferring parsed state merely from `picks_bans` would make cache policy
depend on one feature-specific field and can misclassify parsed matches without draft data. Making
leagues, teams, or professional players long-lived because they appear stable was rejected because
the spec only explicitly grants heroes, patches, and confirmed parsed matches. Sliding expiration
would violate the requirements. A monotonic-only clock cannot survive restart.

## Single coordinated population and shared terminal failure

**Decision**: Represent an active population as a generation-bound lease keyed by cache identity
and random attempt ID. One owner runs the complete existing retry budget outside SQLite; waiters
poll cancellably with bounded jitter. On success, the owner atomically writes one cache entry. On
retry exhaustion, it writes a short-lived sanitized terminal outcome keyed by attempt ID so every
already-attached waiter raises the same failure while a later request starts a new attempt.

**Rationale**: A database uniqueness constraint elects one process without holding a database lock
across slow network work. A finite renewable lease recovers from process death. Keeping completed
failure outcomes separate from the active identity lease is necessary: a later request can retry
immediately without deleting the failure before existing waiters observe it. These outcomes are
coordination records, not cached successful OpenDota responses. The stored failure contains only
the stable code, masked message, retry flags, and optional status—not request headers, upstream
bodies, or credentials.

**Alternatives considered**: Holding an exclusive transaction during HTTP retries blocks all cache
writes. A per-process async lock does not coordinate distinct MCP processes. Caching failures under
the response identity risks serving them as data and prevents a later retry. Deleting the only
failed lease as soon as a new request arrives can cause current waiters to miss the shared outcome.

## Capacity, integrity, and eviction

**Decision**: Bound the retained SQLite main database to 1 GiB by default, configurable in bytes.
Reject a response that cannot fit an otherwise empty initialized store before eviction. For an
eligible write, remove expired records first and then complete LRU response records in
one transaction; commit only within the configured page bound. Store payload length and SHA-256,
verify both plus JSON decoding on every read, and never expose an incomplete row.

**Rationale**: SQLite atomic transactions make an interrupted insert invisible and allow failed
capacity work to roll back candidate evictions. Full auto-vacuum and page limits make allocated
retained storage observable and bounded. Deterministic `(last_used_at, created_at, digest)` ordering
implements LRU under ties. A reader copies a complete committed BLOB before eviction can affect its
caller. Integrity verification handles media damage or manual corruption; an invalid row is a miss
and triggers ordinary upstream retrieval.

**Alternatives considered**: Evicting first for an oversized response violates the requirement to
preserve unrelated entries. Trusting a BLOB solely because the SQLite row exists can return damaged
content. Size-only or FIFO eviction ignores actual reuse. Unbounded metadata/counters alongside
bounded blobs would violate the common capacity model.

## Preserve the existing process-local pagination cache

**Decision**: Keep the existing `SnapshotRegistry` unchanged and outside SQLite. It continues to
materialize normalized and filtered match summaries once, retain at most 32 active traversals for
30 minutes, and use opaque rotating single-use tokens. Process replacement continues to require a
new traversal.

**Rationale**: The current pagination cache already solves the demonstrated need: deterministic,
bounded traversal within a local MCP process without repeating transformation and filtering for
each page. Persisting only traversal metadata and source response identities would make every
continuation reload raw JSON and rerun those transformations. Persisting complete transformed
snapshots would instead couple durable storage to MCP representations. The main new benefit of
either design is cross-process continuation, which is unlikely for this local stdio MCP and does
not justify new schema, lifecycle, capacity, concurrency, inspection, and migration behavior.
Keeping the two caches reflects their different purposes: SQLite reuses upstream responses across
process lifetimes, while the in-memory registry serves short-lived traversal state.

**Alternatives considered**: SQLite traversal metadata referencing cached raw sources was rejected
because it adds repeated page-time transformation and makes continuations depend on every source
entry remaining valid. Persisting shaped snapshots was rejected because it creates durable MCP
representation compatibility concerns. A unified cache abstraction was rejected because sharing a
storage mechanism provides no demonstrated user benefit. Stateless or upstream-offset pagination
remains unsuitable because the existing snapshot contract prevents repeats and skips when source
collections change.

## Inspection and full removal

**Decision**: Extend the existing console entry point with `cache info`, bounded/filterable
`cache entries`, and explicitly confirmed `cache clear --yes`. No arguments must continue to launch
protocol-only stdio. Human output is default; `--json` provides bounded structured output. Entry
pages default to 50 and max at 500.

**Rationale**: A management CLI works with no active MCP process, satisfies the local operator use
case, and avoids expanding the three-tool agent surface. Summary counters are maintained
transactionally with entry events and therefore survive process/computer restarts. Full removal
deletes response entries, population state, and counters in one transaction while incrementing
an internal generation. In-flight work captured the old generation and cannot write afterward;
readers that already copied bytes finish safely.

**Alternatives considered**: An MCP administration tool cannot work independently of a running
server and mixes destructive operator work into the agent surface. Unbounded entry dumps risk slow
commands and secret/context leakage. Deleting the database file while processes hold it has
platform-specific inode/race behavior. Clearing rows without a generation permits pre-clear HTTP
work to repopulate the cache.
