# Data Model: Shared OpenDota Response Cache

## Overview

One owner-only SQLite database stores upstream response entries, process coordination, aggregate
usage counters, and an internal clear generation. Timestamps are UTC Unix seconds in storage and
render as ISO 8601 `Z` values. Cache identity digests use lowercase SHA-256 hex. JSON fields use
canonical UTF-8 JSON.

Only `Response Entry.payload` contains reusable response content, and that content is the complete
successful OpenDota JSON body. Population records are coordination metadata, not successful cached
responses. Existing pagination snapshots remain process-local objects defined by feature 001 and
are not part of this persistent model.

## Entities

### Cache Control

Singleton state that makes destructive clearing safe across live processes.

| Field | Type | Rules |
|---|---|---|
| `id` | integer | Constant `1`; exactly one row |
| `generation` | integer | Nonnegative; increments atomically on every confirmed full clear |
| `schema_version` | integer | Supported persistent schema revision; independent of MCP package version |
| `created_at` | number | Database creation UTC epoch |

`generation` is internal synchronization state. It is not response content or usage metadata and
therefore remains after a clear.

### Response Entry

A complete, successful upstream OpenDota JSON response eligible for reuse.

| Field | Type | Rules |
|---|---|---|
| `key_digest` | string | Primary key; SHA-256 of canonical Cache Identity |
| `api_contract` | string | Stable OpenDota contract namespace, not MCP package version |
| `operation` | string | One of the explicitly supported typed client GET operations |
| `safe_description` | string | Bounded operation plus public selectors; no credentials/headers |
| `payload` | bytes | Complete decoded HTTP response body containing valid JSON |
| `payload_digest` | string | SHA-256 of `payload`; verified before every hit |
| `stored_size` | integer | Positive payload byte length; must equal payload length |
| `category` | enum | `short` or `long` |
| `created_at` | number | Successful storage UTC epoch |
| `expires_at` | number | Exactly `created_at + 900` or `created_at + 86400` |
| `last_used_at` | number | Initially `created_at`; updated on a valid hit |
| `reuse_count` | integer | Nonnegative; initially `0`, incremented on each valid hit |
| `generation` | integer | Must match Cache Control generation at insertion |

Relationships:

- At most one Active Population exists for the same `key_digest`.

Validation:

- `payload` must decode as JSON before insertion and again on read.
- `payload_digest`, `stored_size`, operation, and category must be internally consistent.
- Eligibility is `current_utc_epoch < expires_at`; reuse never changes `expires_at`.
- No incomplete/write-in-progress status exists: uncommitted rows are invisible.

### Cache Identity

An immutable value constructed in memory; canonical identity JSON is not required in inspection
output.

| Field | Type | Rules |
|---|---|---|
| `api_contract` | string | Constant identifying the supported OpenDota API contract |
| `source` | string | Normalized scheme, host, port, and base path; no query/userinfo |
| `method` | string | Constant `GET` for this feature |
| `operation` | string | Stable typed operation name |
| `path_inputs` | object | Every path value used to construct the GET URL, typed and key-sorted |
| `query_inputs` | object | Complete upstream query mapping after explicit exclusions, typed/canonical; all unclassified parameters are included |
| `digest` | string | SHA-256 of canonical JSON of the preceding fields |
| `safe_description` | string | Bounded operation/public-selector rendering |

Identity construction is fail-closed for GET inputs: every path/query value used to build the URL
is presumed content-altering. Before canonicalization, only names on a centralized reviewed
non-content-altering query exclusion list are removed; the initial list is `api_key`. Adding an
exclusion requires official-contract verification and regression coverage proving intentional
identity equivalence. Unknown parameters are never omitted by naming pattern or by lack of an
operation-specific declaration.

Forbidden identity material includes Authorization values, API keys, arbitrary fixed client
headers, raw URLs with query/userinfo, MCP field-group selectors, caller/harness identity, process
ID, session ID, and MCP package version.

### Freshness Classification

An explicit code policy applied after successful payload decoding and before insertion.

| Operation/predicate | Category | TTL |
|---|---|---|
| `get_heroes` | `long` | 86,400 seconds |
| `get_patches` | `long` | 86,400 seconds |
| `get_match` and payload `version` is a non-boolean positive integer | `long` | 86,400 seconds |
| Every other response, including unconfirmed match parse state | `short` | 900 seconds |

No data-driven configuration can silently add a long-lived operation in version one; extensions
require a reviewed code change and tests.

### Usage Summary

Singleton persistent aggregate counters plus computed capacity values.

| Field | Type | Rules |
|---|---|---|
| `id` | integer | Constant `1` |
| `hits` | integer | Valid response-entry reuses only |
| `misses` | integer | Eligible lookups with no valid entry, including expired/corrupt entries |
| `writes` | integer | Successfully committed new/replacement response entries |
| `expirations` | integer | Response entries removed because their fixed expiry elapsed |
| `evictions` | integer | Valid response entries removed for capacity |
| `bypasses` | integer | Requests that could not use cache storage due to cache failure/unavailability |

All persisted counters are nonnegative and changed in the same transaction as their corresponding
event when possible. `entry_count`, `stored_payload_bytes`, `allocated_database_bytes`, and
`configured_max_bytes` are computed consistently for `cache info`.
Confirmed clear deletes old usage state and creates a zeroed row; the clear itself is not counted.

### Active Population

A renewable, generation-bound lease electing one upstream owner for a missing response.

| Field | Type | Rules |
|---|---|---|
| `key_digest` | string | Primary key; target Response Entry identity |
| `attempt_id` | string | Unique cryptographically random attempt identifier |
| `owner_id` | string | Random process-instance owner identifier; not displayed |
| `generation` | integer | Cache generation observed at acquisition |
| `started_at` | number | UTC epoch |
| `lease_expires_at` | number | Finite UTC deadline; renewable only by owner |

Only the matching owner/attempt/generation can renew, complete, or release the lease. An expired
lease may be atomically replaced. No database transaction remains open while the owner performs
HTTP I/O, backoff, or sleep.

### Population Outcome

Short-lived terminal failure metadata for callers that already joined one coordinated attempt.

| Field | Type | Rules |
|---|---|---|
| `attempt_id` | string | Primary key; identifies the finished attempt |
| `key_digest` | string | Failed response identity |
| `generation` | integer | Attempt's generation |
| `error_code` | string | Stable masked upstream code |
| `message` | string | Bounded secret-safe message |
| `status_code` | integer/null | Safe HTTP status when available |
| `retry_exhausted` | boolean | True for the required shared final failure case |
| `retryable_later` | boolean | Existing upstream error contract value |
| `completed_at` | number | UTC epoch |
| `retain_until` | number | Bounded waiter-observation deadline |

Population Outcomes never satisfy response lookup, never increment hits/writes, never contain an
upstream body or credential, and are pruned after `retain_until` or clear.

### Existing Pagination Snapshot (non-persistent boundary)

The existing `SnapshotRegistry` remains the authoritative pagination model from feature 001. It
stores immutable normalized match summaries, query fingerprint, page size, offset, current opaque
token, and timestamps in process memory. Its 30-minute lifetime, 32-traversal LRU capacity, token
rotation, replay rejection, and restart-required behavior are unchanged.

There is no SQLite table, foreign key, response-entry reference, capacity counter, inspection row,
or clear transition for pagination. A continuation reads its materialized transformed records and
does not rehydrate them from `Response Entry.payload`.

## State Transitions

### Response lookup/population

```text
ABSENT/EXPIRED/CORRUPT
  -> MISS
  -> JOIN(existing live attempt) OR OWN(new/expired lease)

OWN
  -> SUCCESS + same generation + capacity available -> COMPLETE ENTRY
  -> SUCCESS + oversized/unavailable/full/cleared    -> RETURN FRESH, NOT STORED
  -> RETRY EXHAUSTED                                  -> TERMINAL OUTCOME
  -> CANCEL/OWNER LOSS                                -> RELEASE OR LEASE EXPIRY

COMPLETE ENTRY
  -> VALID READ  -> HIT (fixed expiry; reuse/last-use increment)
  -> TIME PASSES -> EXPIRED -> DELETE
  -> CAPACITY    -> EVICTED -> DELETE
  -> CLEAR       -> DELETE
  -> INTEGRITY FAILURE -> CORRUPT -> DELETE/BYPASS
```

### Full clear

```text
generation N
  -> one immediate transaction
     - delete responses, populations, outcomes, old counters
     - set generation N+1
     - insert zero counters
  -> commit

in-flight completion tagged N -> may return to original caller; storage write rejected
pre-clear waiter tagged N      -> restart/bypass outcome; cannot join generation N+1
new work tagged N+1            -> may populate normally
```

## Indexes and Bounded Queries

- Response entries: `(expires_at)`, `(last_used_at, created_at, key_digest)`,
  `(operation, category, last_used_at, key_digest)`.
- Population outcomes: `(retain_until)`.
- CLI detail pagination uses a deterministic `(last_used_at DESC, stable digest ASC)` seek cursor;
  it never uses an unbounded offset scan or returns more than 500 rows.
