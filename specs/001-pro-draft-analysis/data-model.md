# Phase 1 Data Model: Professional Draft Analysis MCP

The implementation uses typed Pydantic models at the upstream boundary and for MCP structured output. Upstream models accept missing/unknown fields; public models expose only the stable fields below and distinguish `null` from `false` or `0`.

## Common value objects

### TeamIdentity

| Field | Type | Rules |
|---|---|---|
| `team_id` | integer or null | Positive stable OpenDota ID when available |
| `name` | string or null | Never inferred when upstream is missing |
| `tag` | string or null | Included for resolved team/candidate identity, not required in match-time summaries |

### HeroIdentity

| Field | Type | Rules |
|---|---|---|
| `hero_id` | integer | Positive upstream ID retained even when the label is missing |
| `localized_name` | string or null | Resolved from documented hero data |

### PlayerIdentity

| Field | Type | Rules |
|---|---|---|
| `account_id` | integer or null | Steam32 account ID; null only when no unambiguous mapping exists |
| `professional_name` | string or null | Match record name, then authoritative pro-player catalog name |
| `display_identity` | string or integer or null | Professional name first, otherwise Steam32 ID, otherwise null |
| `identity_source` | enum | `professional_name`, `steam32_fallback`, `unavailable`, or `ambiguous` |

`personaname` is deliberately absent and must never populate any public field.

### DataWarning

| Field | Type | Rules |
|---|---|---|
| `status` | enum | Non-OK discriminator: `warning` for data-quality degradation or `needs_selection` for caller disambiguation |
| `code` | string enum | Stable machine-actionable warning code |
| `message` | string | Concise explanation without credentials/raw payloads |
| `path` | string or absent | Domain path such as `draft_actions[3].hero.localized_name`; absent for response-level selection warnings |

Warnings live on the affected match, action, identity, or collection. A response-level warning is used only for a collection-wide anomaly or `needs_selection`. Every `warnings` property is optional and, when present, contains at least one warning; empty arrays are never serialized.

## Draft entities

### DraftAction

| Field | Type | Rules |
|---|---|---|
| `source_index` | integer | Zero-based upstream array position; always present |
| `order` | integer or null | Supplied upstream value retained unchanged |
| `action_type` | enum | `pick` or `ban` |
| `acting_side` | enum or null | `radiant`, `dire`, or null for an unknown upstream team code |
| `acting_team` | TeamIdentity | Match-time team identity for the acting side |
| `hero` | HeroIdentity | Stable hero ID plus nullable label |
| `player` | PlayerIdentity or null | Required only for picks when uniquely mappable; always null for bans |
| `timing` | DraftTiming or absent | Added only when `draft_timing` is requested |
| `warnings` | non-empty DataWarning[] or absent | Action-local missing/ambiguous data; absent when there is none |

### DraftTiming

| Field | Type | Rules |
|---|---|---|
| `extra_time_seconds` | integer or null | From the uniquely corresponding upstream timing item |
| `total_time_taken_seconds` | integer or null | From the uniquely corresponding upstream timing item |

Timing is matched by authoritative action order where unique. If timing cannot be matched uniquely, it remains null and an action warning explains why.

### MatchDraft

| Field | Type | Rules |
|---|---|---|
| `match_id` | integer | Requested stable ID |
| `start_time` | UTC date-time or null | ISO 8601 with `Z` when available |
| `match_date` | UTC date or null | Derived from `start_time` |
| `patch_id` | integer or null | Retained even when patch label is absent |
| `patch_version` | string or null | Resolved from patch constants |
| `radiant_team` | TeamIdentity | Match-time identity |
| `dire_team` | TeamIdentity | Match-time identity |
| `ordering_quality` | enum | `authoritative` or `degraded` |
| `completeness` | enum | `complete` or `partial` |
| `draft_actions` | DraftAction[] | All upstream actions; never silently dropped |
| `warnings` | non-empty DataWarning[] or absent | Match-level data quality issues; absent when there is none |
| optional groups | objects | Present only when requested; defined in the contract |

### DraftOutcome

A batch preserves first-occurrence input order after silently removing duplicate requested IDs. Each item is a sparse union:

- A successful item has `match_id` and `draft`; it has no generic `status` or `error` property.
- A failed item has `match_id` and a non-empty `error`; it has no `draft` placeholder. The nested `error.status` is `unavailable`, `not_professional`, `not_parsed`, or `upstream_error`.

A valid partial draft remains a successful item with `completeness: partial` and one or more warnings carrying `status: warning`; a missing draft array/players needed for requested evidence becomes `not_parsed` only when the match cannot support the core scenario.

## Discovery entities

### LeagueIdentity

| Field | Type | Rules |
|---|---|---|
| `league_id` | integer | Positive stable ID |
| `name` | string or null | Nullable upstream label |
| `tier` | string or null | Used for eligibility/candidate context, not inferred |

### TournamentMatchSummary

Fields: `match_id`, UTC `start_time`, `league`, `radiant_team`, `dire_team`, nullable `winner` (`radiant`/`dire`), nullable `radiant_score`, nullable `dire_score`, and optional non-empty record-scoped `warnings`.

### TeamMatchSummary

Fields: `match_id`, UTC `start_time`, `league`, `selected_team`, `opponent`, `selected_team_side` (`radiant`/`dire`), nullable `selected_team_result` (`win`/`loss`), nullable Radiant/Dire scores, and optional non-empty record-scoped `warnings`.

### IdentityCandidate

League candidates contain stable ID, name, and tier. Team candidates contain stable ID, name, tag, and nullable UTC last-match time. Candidate arrays contain at most 10 items in deterministic rank order.

### PageMetadata

| Field | Type | Rules |
|---|---|---|
| `returned_count` | integer | `0..page_size` |
| `page_size` | integer | `1..100`; defaults to 20 on a first page |
| `continuation_token` | string or null | Opaque, single-use, and non-null only when more records exist |
| `terminal` | boolean | True exactly when no next page exists |
| `snapshot_expires_at` | UTC date-time or null | Present on nonterminal pages to make restart timing explicit |

### TraversalSnapshot (internal)

Fields: random snapshot ID, tool kind, canonical query fingerprint, normalized match summaries, fixed page size, next offset, creation/expiry/last-access timestamps, and current token hash. Snapshots expire after 30 minutes, rotate tokens after a successful page, and are evicted least-recently-used above 32 concurrent traversals. There is no per-snapshot match-record cap.

Relationships:

- One snapshot belongs to exactly one tournament or team query.
- One snapshot contains zero or more immutable summary records.
- A continuation token references one snapshot and one next offset but reveals neither.
- One prior token is invalidated when its successor is issued.

## Error entity

### ToolErrorDetail

Fields: required non-OK `status`, stable `code`, human-readable `message`, `tool`, optional `target` (match/league/team/token), `retry_exhausted` boolean, `retryable_later` boolean, and optional `valid_values`/`restart_required`. Tool-level failures use `status: error`; draft-item failures use the more specific `unavailable`, `not_professional`, `not_parsed`, or `upstream_error`. It never contains request headers, API keys, raw credential-bearing URLs, tracebacks, or unbounded upstream bodies.

## Validation rules

- Draft IDs: array length 1–10 before deduplication; each value is a positive integer; duplicates are silently omitted after first occurrence and produce no response field or diagnostic.
- Collection first page: exactly one of ID or nonblank name query; positive ID; page size 1–100.
- Continuation: token may stand alone; any repeated selector/filter/page size must equal the snapshot fingerprint.
- Dates: exact `YYYY-MM-DD`, start not after end, both inclusive in UTC.
- Side/result: only `radiant`/`dire` and `win`/`loss`.
- Include groups: unique subset of `competition`, `result`, `draft_timing`, `provenance`; any unknown value rejects the entire request.
- Authoritative order: a draft with `n` actions has integer values exactly equal to `0..n-1`. Otherwise the entire draft uses source-array sequence and `degraded` quality.
- Tournament/team summaries sort by `(start_time, match_id)` descending; identical duplicate upstream records collapse silently, while conflicting records sharing a match ID collapse deterministically with a warning.

## State transitions

```text
first collection request
  -> validation/selection error
  -> needs_selection
  -> snapshot active + first page

active snapshot + valid current token
  -> rotated token + next page
  -> terminal page + snapshot deleted

active snapshot
  -> expired/evicted/restarted process -> stale token error + restart guidance
  -> replayed/mismatched/cross-tool token -> invalid token error
```
