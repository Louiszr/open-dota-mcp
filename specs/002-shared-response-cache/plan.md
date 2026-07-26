# Implementation Plan: Shared OpenDota Response Cache

**Branch**: `002-shared-response-cache` | **Date**: 2026-07-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-shared-response-cache/spec.md`

## Summary

Add one per-operating-system-user, SQLite-backed cache beneath the existing typed OpenDota
client. Cache identities are secret-free hashes of the OpenDota contract version, source,
operation, path inputs, and the complete canonical query mapping used to build each GET URL. Query
parameters are content-altering by default; only an explicit reviewed exclusion list may omit a
known non-content-altering parameter such as API-key authentication material. Complete successful
upstream JSON payloads are stored before MCP response shaping, default to a fixed 15-minute
lifetime, and receive a fixed 1-day lifetime only for heroes, patch constants, and match payloads
with a confirmed parse version. Short SQLite transactions coordinate cross-process population,
integrity checks, generation-safe clearing, persistent counters, and bounded LRU eviction. Existing process-local
pagination snapshots remain unchanged: transformed records are materialized once, retained for
30 minutes within the 32-traversal registry, and are not persisted or reconstructed from cached
raw JSON. Existing MCP tool schemas stay unchanged; a bounded `open-dota-mcp cache` CLI provides
independent inspection and confirmed full removal.

## Technical Context

**Language/Version**: Python 3.13+

**Primary Dependencies**: FastMCP, httpx, Pydantic (through FastMCP), and Python's standard
`sqlite3`, `hashlib`, `json`, `argparse`, and filesystem APIs; development dependencies pytest,
pytest-asyncio, and Ruff

**Storage**: One user-owned SQLite database in the local user cache directory, using complete
upstream JSON blobs and transactional metadata/counters/population leases; default retained
database capacity 1 GiB. Existing pagination storage remains a separate, process-local bounded
memory registry.

**Testing**: pytest and pytest-asyncio with `httpx.MockTransport`, temporary SQLite databases,
injectable wall/monotonic clocks, subprocess and multi-process contention tests, FastMCP
contract tests, and CLI subprocess tests

**Target Platform**: Local macOS or Linux process launched by Codex or another standards-compliant
MCP client over stdio; all cooperating processes run as the same operating-system user

**Project Type**: Single Python package providing a local stdio MCP service and local management
CLI

**Performance Goals**: Reuse 100% of valid retained entries without upstream I/O; coordinate 20
equivalent concurrent requests into one population attempt; report a 10,000-entry summary in
under 2 seconds; keep every committed retained database at or below configured capacity

**Constraints**: Default TTL 900 seconds, explicit long TTL 86,400 seconds, default capacity
1 GiB, fixed absolute expiry, no stale serving, no successful failure caching, no secret-bearing
identity material, user-only filesystem access, protocol-only stdout during MCP stdio operation,
fail-closed inclusion of new GET query parameters in cache identities, cache failure must degrade
to normal upstream behavior, and tests remain offline/deterministic

**Scale/Scope**: One computer and user account; the existing nine OpenDota GET operations and
three MCP tools; up to 10,000 inspected entries; 50-entry default/500-entry maximum CLI detail
pages; one shared cache generation across any number of local MCP processes

## Constitution Check

*GATE: Passed before Phase 0 and re-checked after Phase 1.*

- **Scope — PASS**: The cache directly addresses demonstrated unauthenticated call pressure,
  restart persistence, bounded storage, and operator visibility. It deliberately preserves the
  already-bounded process-local pagination registry and adds no
  remote cache, web UI, encryption layer, endpoint expansion, or cache administration MCP tool.
- **OpenDota contract — PASS**: `research.md` re-verifies the official OpenDota OpenAPI source and
  inventories every existing GET operation. The cache wraps the existing client without changing
  endpoint parameters, response validation, authentication, timeouts, three-attempt retry policy,
  `Retry-After` handling, jittered delay budget, or cancellation propagation. Only completed 2xx
  JSON content is retained.
- **Testing — PASS**: Public cache/CLI functions and unchanged MCP tools have planned pytest
  coverage. Risk-based internal coverage includes canonical identities, default inclusion of new
  GET query parameters, reviewed credential exclusion, TTL classification,
  integrity rejection, clock movement, capacity/LRU behavior, SQLite contention, process crash,
  shared success/failure, generation-safe clear, user permissions, cache-unavailable bypass, and
  regression coverage proving pagination snapshots remain process-local and unchanged.
- **Quality — PASS**: New public APIs will be fully typed and Google-documented. The standard
  library storage choice avoids an extra persistence dependency, and all code remains subject to
  configured Ruff lint/format gates.
- **Independent QA — PASS (implementation gate)**: Completion requires a separate non-implementing
  QA sub-agent to audit public/risk-based tests and run `ruff check`, `ruff format --check`, and
  the full pytest suite after remediation.
- **Interoperability — PASS**: The three typed FastMCP tools and their response schemas remain
  unchanged. Cache diagnostics use logging/stderr, stdio stdout remains protocol-only, and Codex
  plus generic protocol subprocess tests cover cache hits and restart reuse.
- **Agent ergonomics — PASS**: Existing slim cores, additive draft groups, focused selectors, and
  20/100 MCP pages remain authoritative. Cache hits return raw upstream content to the same shaping
  layer as misses. Pagination tokens retain their existing process-local, opaque, rotating,
  30-minute behavior and 32-traversal bound. The management interface is a bounded local CLI, not
  agent-context payload added to every MCP result.

### Post-design re-check

Phase 1 preserves every gate. The data model limits SQLite to response entries, coordination, and
usage metadata; the contract makes every GET query parameter identity-bearing by default and
explicitly excludes only reviewed non-content-altering inputs, MCP `include` groups, and MCP
continuation state. CLI entry output has filters plus 50/500 pagination
bounds. Keeping the existing pagination registry satisfies the immediate bounded-pagination need
without speculative cross-process state or repeated raw-payload transformation. Generation checks
make live response-cache removal safe. No constitution exception is required.

## Project Structure

### Documentation (this feature)

```text
specs/002-shared-response-cache/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── cache-interface.md
└── tasks.md                     # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
pyproject.toml
README.md
.env.example
src/
└── open_dota_mcp/
    ├── __init__.py
    ├── __main__.py              # Preserve no-argument stdio; dispatch `cache` subcommands
    ├── cache/
    │   ├── __init__.py
    │   ├── identity.py          # Canonical secret-free identities and safe descriptions
    │   ├── policy.py            # Explicit TTL classification
    │   ├── store.py             # SQLite entries, counters, leases, eviction, clear
    │   └── cli.py               # Bounded info/entries/clear management interface
    ├── clients/
    │   └── opendota.py          # Cache lookup/population around successful GET JSON
    ├── models/
    │   └── common.py
    ├── pagination.py            # Existing process-local transformed snapshots; unchanged
    ├── config.py                # Cache path and configured maximum size
    ├── errors.py
    ├── server.py
    └── services/
        ├── drafts.py
        ├── identity.py
        └── matches.py
tests/
├── contract/
│   ├── test_cache_cli.py
│   ├── test_draft_tool.py
│   ├── test_team_tool.py
│   └── test_tournament_tool.py
├── integration/
│   ├── test_cache_lifecycle.py
│   ├── test_cache_multiprocess.py
│   ├── test_discovery_to_draft.py
│   └── test_stdio.py
└── unit/
    ├── test_cache_identity.py
    ├── test_cache_policy.py
    ├── test_cache_store.py
    ├── test_config.py
    ├── test_opendota_client.py
    └── test_pagination.py
```

**Structure Decision**: Retain the existing single `src`-layout package. A focused `cache`
subpackage owns persistence policy without becoming a generic repository layer. The HTTP client
is the only upstream response-cache boundary, services continue to shape domain responses, and
`pagination.py` remains independent process-local traversal storage. The existing console entry point
starts stdio when no arguments are present and dispatches only explicit `cache` subcommands.

## Implementation Design

### Storage, ownership, and integrity

- Resolve the default database under `~/Library/Caches/open-dota-mcp/` on macOS and
  `${XDG_CACHE_HOME:-~/.cache}/open-dota-mcp/` on Linux; allow `OPENDOTA_CACHE_DIR` for testing and
  operator control. Reject symlinks, non-owner paths, and files not owned by the current user.
  Create the directory as `0700` and the database as `0600`; revalidate before management writes.
- Use SQLite rollback-journal transactions with a finite busy timeout, foreign keys, full
  auto-vacuum initialized before schema creation, and an explicit application/user schema version.
  `max_page_count` supplies a hard retained main-database bound; page count times page size is the
  operator-visible allocated size. Rollback journals are temporary atomic-commit files, never
  retained entries. Cache operations run off the async event loop and hold transactions only for
  metadata/BLOB reads or writes, never during HTTP I/O or retry sleeps.
- Insert only a fully received, successfully JSON-decoded payload and its SHA-256 digest in one
  transaction. Readers copy and verify the complete BLOB before returning it. Invalid JSON,
  digest mismatch, missing content, schema/database errors, and interrupted transactions never
  produce a hit; the affected entry is discarded when safe and the ordinary upstream path runs.
- Treat SQLite unavailability, permission errors, corruption, lock timeout, or capacity errors as
  cache bypasses. Emit a secret-safe actionable diagnostic on stderr/logging, increment `bypasses`
  when the database remains writable enough to do so, and never convert a cache problem into an
  MCP success or obscure an upstream error.

### Identity and response boundary

- Build canonical JSON from a constant OpenDota API-contract namespace, normalized configured
  source origin/base path, HTTP GET operation name, every path input, and the complete structured
  query-parameter mapping passed to the HTTP client to build the GET URL. Treat every query
  parameter as content-altering by default: after removing only explicitly allowlisted
  non-content-altering parameters, include all remaining names and values without requiring an
  endpoint-specific cache declaration. This makes a newly introduced query parameter change the
  digest automatically and favors safe cache fragmentation over an incorrect cross-parameter hit.
  Normalize mappings recursively, preserve list order when order affects the request, normalize
  semantically unordered sets where the operation contract permits it, and reject non-finite or
  unsupported values. Hash the UTF-8 canonical JSON with SHA-256 for the database primary key.
- Keep the non-content-altering query exclusion list explicit, narrow, and centralized; initially
  it contains only `api_key` authentication material (the current client supplies the configured
  key through `Authorization`, so it normally never reaches query canonicalization).
  Adding an exclusion requires review against the official upstream contract and tests showing
  that changing only that parameter intentionally preserves identity. Never infer exclusions from
  naming patterns or silently omit unknown parameters. Never include `Authorization`, `api_key`,
  `OPENDOTA_API_KEY`, arbitrary fixed client headers, or a credential-bearing URL in identity
  input, descriptions, diagnostics, or inspection. Current IDs and page numbers are public
  OpenDota selectors and may appear in bounded safe descriptions.
- Cache at `OpenDotaClient._get` after finite retries return a successful JSON response but before
  `_get_object`/`_get_list` and all service/MCP transformations. A cache hit is decoded and passed
  through the same top-level validation as a fresh payload. MCP `include` groups are intentionally
  absent from the upstream identity because they shape the already-obtained content afterward.
- Keep the cache namespace tied to the OpenDota contract, not the MCP package version. Compatible
  software upgrades therefore reuse entries; exceptional incompatibility is handled by confirmed
  full-cache removal.

### Freshness and clock behavior

- The classifier defaults every operation to `short` (900 seconds). Only `get_heroes` and
  `get_patches` are statically `long` (86,400 seconds). `get_match` is `long` only when the returned
  object has a non-boolean positive integer OpenDota parse `version`; missing, null, malformed, or
  nonpositive parse versions remain `short`. The explicit operation table is code-reviewed when
  extended.
- Set `created_at` from wall-clock UTC immediately before the successful storage transaction and
  persist `expires_at = created_at + ttl`. Hits, process replacement, restart, and clock changes
  never rewrite either value. Eligibility is `now < expires_at`; equality is expired. A clock
  adjustment can change when the fixed absolute instant is observed but cannot extend the stored
  expiry value.
- Delete expired rows opportunistically and increment `expirations` once per removed entry. Never
  serve stale data and never cache non-2xx responses, retry exhaustion, decoding failures, or
  caller cancellation as successful content.

### Cross-process population and failure sharing

- In a short `BEGIN IMMEDIATE` transaction, a miss records the current cache generation and tries
  to acquire the identity's population lease with a random attempt ID, owner ID, and finite lease
  deadline. The owner performs the existing complete retry budget outside SQLite and renews the
  lease between bounded retry stages when necessary. Other processes poll with bounded jitter and
  cancellation/deadline checks; they do not make an independent OpenDota call while the lease is
  live.
- On success, the owner transaction verifies both attempt ownership and unchanged cache
  generation, performs capacity management, writes the response, increments `writes`, and removes
  the lease. Waiters read that one stored payload. If storage is unavailable after a successful
  fetch, the owner still returns the fresh payload and waiters may fall back independently because
  cache coordination itself is unavailable.
- On final retry exhaustion, the owner writes a short-lived, secret-safe population outcome keyed
  by attempt ID, removes the active lease, and raises the same structured upstream failure. Callers
  already attached to that attempt read and raise that outcome; a later request can immediately
  acquire a new attempt without erasing the prior waiters' outcome. Outcomes are coordination
  metadata, never successful cache entries, and are pruned after the maximum waiter window.
- An expired lease caused by process death can be replaced atomically. Cancellation releases an
  owned lease without manufacturing a shared upstream failure. No SQLite lock is held across
  network I/O, sleeps, or caller response shaping.

### Capacity, LRU, and clear generation

- Validate a configured positive maximum and default it to 1,073,741,824 bytes. Before evicting,
  reject a serialized response that cannot fit the maximum even in an otherwise empty initialized
  store; return it fresh, increment no write, and leave unrelated entries untouched.
- For a cacheable write, remove expired response entries first, then complete least-recently-used
  response entries ordered by `last_used_at`, `created_at`, and digest. Reads and
  writes occur in transactions, so a concurrent reader sees either the old complete BLOB or the
  new complete state. If a writer cannot obtain space without conflicting with active work, it
  bypasses storage. Commit only if `page_count * page_size <= max_bytes`; a failed/full transaction
  rolls back its candidate evictions and write.
- Hits atomically update `last_used_at`, increment per-entry `reuse_count`, and increment aggregate
  `hits`; misses, successful writes, expirations, capacity evictions, and bypasses have distinct
  persistent counters. Inspection reads one consistent snapshot. Full removal transactionally
  deletes response entries, leases, outcomes, and counters, increments an internal generation,
  and reinitializes counters to zero. It does not interact with process-local pagination snapshots.
- Every population captures its starting generation. Completion writes require an exact match, so
  work begun before a completed clear can return to its original caller but cannot repopulate the
  cleared store. A pre-clear waiter that observes the generation change finishes through a
  secret-safe restart/bypass path and cannot silently join the new generation. Work begun afterward
  observes the new generation and may populate normally.

### Existing pagination remains out of SQLite scope

- Preserve `SnapshotRegistry` as the existing process-local in-memory store of normalized,
  filtered match summaries. Keep tool/query binding, single-use opaque token rotation, 20-record
  default pages, 100-record maximum pages, the 30-minute snapshot lifetime, and the 32-traversal
  LRU capacity unchanged.
- A continuation consumes the already-materialized transformed records. It does not reload raw
  response-cache JSON or rerun service transformations and filters for each page. This avoids
  introducing extra work on the common same-process pagination path.
- Do not add pagination tables, source-response references, token rows, pagination counters,
  pagination CLI entries, or clear-generation coupling to SQLite. Process replacement continues
  to invalidate its tokens with the existing actionable restart guidance. Cross-process
  continuation is explicitly out of scope because a local MCP is unlikely to hand an active
  traversal between simultaneous processes and that benefit does not justify a unified cache.

### Local management interface

- Preserve `open-dota-mcp` and `python -m open_dota_mcp` with no arguments as protocol-only stdio.
  Add `cache info`, `cache entries`, and `cache clear --yes`; management commands run without a
  server and may write their human or JSON result to stdout.
- `cache info` reports response entry count, allocated/stored bytes, configured maximum, and exact hits,
  misses, writes, expirations, evictions, and bypasses. `cache entries` defaults to 50, permits at
  most 500, filters by operation/category, sorts deterministically, and returns an opaque next
  cursor when more response rows exist. It exposes only the safe description, category, timestamps, stored
  size, last use, and reuse count.
- `cache clear` does nothing without explicit `--yes` and exits with usage status. Confirmed clear
  reports counts/bytes removed but never entry content or secret-bearing identities. CLI failures
  are actionable on stderr with nonzero status and never attempt an upstream call.

## Complexity Tracking

No constitution violations require justification.
