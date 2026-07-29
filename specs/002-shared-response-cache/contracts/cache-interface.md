# Shared Cache Interface Contract

## Scope and compatibility

This feature does not add an MCP tool or change the three existing MCP input/output schemas.
Every cache hit and fresh response enters the same OpenDota shape validation and MCP transformation
path. Existing slim cores, optional draft groups, collection page size default 20/maximum 100,
structured upstream errors, and stdio behavior remain authoritative under
`specs/001-pro-draft-analysis/contracts/`.

The observable changes are:

- equivalent OpenDota GET requests can reuse valid raw upstream content across MCP processes and
  computer restarts;
- existing process-local continuation snapshots retain their 30-minute lifetime, 32-traversal
  capacity, transformed records, and restart-required behavior;
- a new process-independent local CLI exposes bounded cache inspection and confirmed removal.

## Cache eligibility and identity

Only successful GET responses from the current typed OpenDota client are eligible. Non-2xx
responses, retry exhaustion, malformed JSON, top-level contract failures, cancellation, and any
future mutating operation are not stored as successful entries.

The identity canonical document is logically:

```json
{
  "api_contract": "opendota-public-api-v1",
  "source": "https://api.opendota.com/api",
  "method": "GET",
  "operation": "get_team_matches",
  "path_inputs": {"team_id": 2163},
  "query_inputs": {}
}
```

Object keys are recursively sorted and compactly encoded. Typed scalar values remain distinct;
unsupported/non-finite values are rejected rather than stringified ambiguously. `path_inputs`
contains every value used to construct the path. `query_inputs` begins as the complete structured
mapping passed to the HTTP client to construct the GET URL. Every query parameter is presumed
content-altering, so an unknown or newly introduced parameter is included automatically.
Semantically equivalent parameter mappings produce the same SHA-256 identity. Different source
base paths, operations, IDs, unclassified query values, and upstream page numbers remain distinct.

Before canonicalization, the implementation removes only query names on a centralized, explicit,
code-reviewed non-content-altering exclusion list. The initial list contains only `api_key`
authentication material. New exclusions require review against the official OpenDota contract and
regression tests proving that changing only the excluded parameter intentionally preserves the
identity. Exclusions are never inferred from naming patterns, and new parameters do not require a
cache-code change to become identity-bearing.

The following never enter the identity or stored/displayed description:

- `Authorization`, excluded `api_key` authentication material, `OPENDOTA_API_KEY`, cookies, or the
  current client's fixed request headers;
- URL userinfo or a raw query string;
- MCP caller, harness, session, process, or package version;
- draft `include` values or other transformations applied only after upstream retrieval.

Safe descriptions use the operation and public selectors, for example `get_match(match_id=123)` or
`get_teams_page(page=4)`. They are bounded and never display payload content.

## Freshness contract

| Upstream operation/result | Category | Fixed lifetime |
|---|---|---|
| `get_heroes` | `long` | 1 day (86,400 seconds) |
| `get_patches` | `long` | 1 day (86,400 seconds) |
| `get_match` with positive integer parse `version` | `long` | 1 day (86,400 seconds) |
| `get_match` without confirmed positive integer parse `version` | `short` | 15 minutes (900 seconds) |
| All other current operations | `short` | 15 minutes (900 seconds) |

The lifetime starts only after the complete successful payload is ready to commit. Reuse does not
extend it. At `now == expires_at` the entry is expired. Expired content is never served as fresh or
used as a stale fallback when OpenDota fails.

## Lookup and population outcomes

### Valid hit

1. Verify generation, fixed expiry, stored size, SHA-256, and JSON decoding.
2. Atomically increment aggregate hits, entry reuse count, and last-use time without changing
   creation/expiry.
3. Return upstream content to the existing typed validation/shaping path with no extra MCP fields.

### Miss

An absent, expired, corrupt, or unreadable eligible entry is a miss. Expired/corrupt rows are not
returned. One process may acquire the population attempt; all other equivalent callers attach to
that attempt while its lease is live.

### Coordinated success

The owner runs the existing bounded retry policy. It commits one complete response only if it still
owns the attempt, the clear generation is unchanged, integrity validation succeeds, and capacity
permits. All waiters use that stored payload. Caller-specific MCP shaping occurs independently
after retrieval, so equivalent upstream requests may request different MCP field groups without a
second OpenDota call.

### Coordinated final failure

When the owner exhausts the retry budget, every caller already attached to that attempt receives
the same masked error code/message/status/retry flags. No successful response entry is created. A
request arriving after completion may acquire a new attempt immediately.

### Cache bypass

Permission, lock-timeout, corruption, unavailable storage, unsupported schema, or capacity failure
causes a secret-safe diagnostic and normal OpenDota behavior when possible. A successful fresh
payload is returned even if it cannot be stored. A cache failure never becomes a false successful
payload and never masks the eventual upstream error.

### Oversized response

If one serialized response cannot fit an otherwise empty initialized configured store, return it
fresh but do not store it. Do not evict unrelated entries while deciding this outcome.

## Capacity and eviction

- `OPENDOTA_CACHE_MAX_BYTES` configures a positive retained SQLite database maximum; default
  `1073741824` (1 GiB).
- Capacity cleanup removes expired response entries first, then least recently used valid response
  entries with deterministic tie-breaking.
- Entry BLOB reads and all mutations are transactional. Readers never receive partial bytes;
  process death during a write leaves no visible incomplete entry.
- A capacity write commits only when the allocated main database remains at or below the configured
  maximum. If it cannot commit safely, candidate eviction/write work rolls back and the fresh
  response is returned uncached.
- Counters and coordination metadata live in the same bounded database rather than an unbounded
  side store. Process-local pagination memory is governed independently by its existing fixed
  lifetime and traversal-count bound.

## Pagination boundary

Existing collection inputs, outputs, and `SnapshotRegistry` behavior remain unchanged. For a
nonterminal first page, the process-local registry materializes the normalized and filtered match
summaries and subsequent continuations consume those already-transformed records.

- Tokens remain opaque, tool/query-bound, rotating, and single-use.
- Snapshots retain their fixed 30-minute lifetime and 32-traversal LRU capacity.
- A replacement MCP process cannot consume a prior process's token and receives the existing
  recoverable restart guidance.
- Pagination data is not written to SQLite, counted toward response-cache capacity, shown by cache
  inspection, or removed by `cache clear`.
- Continuation does not reload raw cached OpenDota payloads or rerun service transformation and
  filtering on each page.

Cross-process continuation is not part of this feature's contract.

## Configuration contract

| Environment variable | Default | Validation/behavior |
|---|---|---|
| `OPENDOTA_CACHE_DIR` | Platform user-cache directory | Absolute or resolved user-owned local directory; no symlink/wrong-owner target |
| `OPENDOTA_CACHE_MAX_BYTES` | `1073741824` | Positive integer large enough for initialized store |

Invalid cache configuration fails startup/CLI validation with the setting name and no secret value.
The 900/86,400-second lifetimes, finite SQLite wait, and population lease policy are fixed code
contracts rather than speculative environment configuration. The API key remains excluded from
representations. Tests inject paths and clocks without changing public behavior.

## Management CLI

With no arguments, `open-dota-mcp` and `python -m open_dota_mcp` continue to start stdio and must
not print a banner. Only explicit `cache` subcommands use ordinary CLI stdout/stderr.

### `cache info`

```text
open-dota-mcp cache info [--json]
python -m open_dota_mcp cache info [--json]
```

Required fields:

| Field | Type |
|---|---|
| `entry_count` | nonnegative integer |
| `stored_payload_bytes` | nonnegative integer |
| `allocated_database_bytes` | nonnegative integer |
| `configured_max_bytes` | positive integer |
| `hits` | nonnegative integer |
| `misses` | nonnegative integer |
| `writes` | nonnegative integer |
| `expirations` | nonnegative integer |
| `evictions` | nonnegative integer |
| `bypasses` | nonnegative integer |

`--json` returns one JSON object. Human output names the same values. The command performs no
upstream request and should complete under two seconds for 10,000 entries on a typical development
computer.

### `cache entries`

```text
open-dota-mcp cache entries \
  [--operation NAME] [--category short|long] \
  [--limit 1..500] [--cursor OPAQUE] [--json]
```

Default limit is 50; maximum is 500. Filters combine with AND semantics. Results sort by last use
descending with stable digest tie-breaking. Each item contains only:

```json
{
  "kind": "response",
  "safe_description": "get_match(match_id=123)",
  "operation": "get_match",
  "category": "long",
  "created_at": "2026-07-25T12:00:00Z",
  "expires_at": "2026-07-26T12:00:00Z",
  "stored_size": 12345,
  "last_used_at": "2026-07-25T12:30:00Z",
  "reuse_count": 2
}
```

The page envelope contains `returned_count`, `limit`, and nullable opaque `next_cursor`. Invalid
limit/filter/cursor input exits nonzero before reading entry payloads. Output never contains raw
identity JSON, identity/token digests, response content, credentials, headers, or full URLs.

### `cache clear`

```text
open-dota-mcp cache clear --yes [--json]
```

Without `--yes`, no state changes and the command exits with usage status plus an instruction to
repeat with `--yes`. With `--yes`, one transaction:

1. increments the internal generation;
2. removes all response entries, active populations/outcomes, and prior usage counters;
3. creates zeroed usage counters and commits;
4. reports removed response counts and bytes (not content or keys).

The operation does not inspect or mutate process-local pagination snapshots owned by active MCP
processes.

Existing readers that already copied a complete payload may finish. Every population begun under
the prior generation is forbidden from writing, even if its OpenDota request later succeeds.
Requests begun after clear may populate under the new generation. Active MCP processes need not
stop.

## Diagnostics and exit behavior

- Cache/runtime diagnostics use standard error or framework logging; MCP stdio stdout remains
  protocol-only.
- CLI success is exit status 0. Invalid input/confirmation is usage status 2. Unavailable,
  wrong-owner, corrupt, or unsupported cache state is a nonzero operational status with an
  actionable secret-safe message.
- Routine MCP payloads do not gain cache-hit fields. Operators use the CLI counters, avoiding
  repeated response noise and preserving stable MCP schemas.
