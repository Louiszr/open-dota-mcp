# Implementation Plan: Professional Draft Analysis MCP

**Branch**: `001-pro-draft-analysis` | **Date**: 2026-07-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-pro-draft-analysis/spec.md`

## Summary

Build a local, read-only Python 3.13 stdio MCP server with exactly three FastMCP tools: retrieve ordered drafts for 1–10 professional match IDs, page through a professional tournament's matches, and page/filter a professional team's matches. An asynchronous `httpx` client will consume only documented OpenDota endpoints, translate their permissive records into typed domain responses, retry safe transient failures within a finite budget, and keep optional credentials out of output and logs. Rich draft details use four additive field groups; collection results use a slim fixed record and short-lived in-memory snapshots so opaque continuation tokens remain deterministic even when new matches arrive. Responses silently de-duplicate requested match IDs and use sparse diagnostics: successful results omit generic status and empty warning/error fields, while non-OK status lives inside the diagnostic that explains it.

## Technical Context

**Language/Version**: Python 3.13+

**Primary Dependencies**: FastMCP, httpx, Pydantic (through FastMCP); development dependencies pytest, pytest-asyncio, Ruff

**Storage**: No persistent storage; process-local, 30-minute traversal snapshots for deterministic continuation pagination

**Testing**: pytest and pytest-asyncio with `httpx.MockTransport`/fixtures, FastMCP in-memory client tests, and one stdio subprocess compatibility test

**Target Platform**: Local macOS or Linux process launched by a standards-compliant MCP client over stdio

**Project Type**: Single Python package and local MCP service

**Performance Goals**: Bound every discovery page to 100 records and every draft request to 10 distinct matches; avoid raw OpenDota payloads; complete fixture-backed tool calls without real sleeps or network access; allow a known-ID discovery-to-draft workflow in two calls

**Constraints**: Read-only OpenDota access; public access must work without a key; stdout is protocol-only; UTC timestamps; no persistent/private data cache; finite retries and cancellation propagation; deterministic snapshot traversal; offline default tests

**Scale/Scope**: One local user, exactly three public tools, 1–10 match drafts per call, 20-record default/100-record maximum pages, and all eligible tournament matches obtainable across pages without a fixed total ceiling

## Constitution Check

*GATE: Passed before Phase 0 and re-checked after Phase 1.*

- **Scope — PASS**: The design exposes only the three required read-only capabilities. It adds no UI, database, prediction, write operation, remote transport, or generalized OpenDota explorer.
- **OpenDota contract — PASS**: `research.md` records the official OpenAPI 31.1.0 endpoints, parameters, fields, authentication model, and upstream pagination gaps. The client retries only safe GET requests on 429, eligible connection/timeout failures, and 5xx responses, with at most three attempts, bounded exponential jitter, valid `Retry-After` support, a 10-second retry-delay budget, and immediate cancellation/deadline propagation.
- **Testing — PASS**: Contract tests cover every tool's slim output, draft field groups, invalid groups, selectors, filters, pagination, ambiguity, sparse diagnostic omission, silent input de-duplication, and structured errors. Unit/integration tests cover transformations, partial data, order degradation, snapshot traversal, malformed upstream data, transient recovery, exhaustion, `Retry-After`, and cancellation without live calls or delays.
- **Quality — PASS**: Public functions/classes/tools have complete annotations and Google-style docstrings. `pyproject.toml` configures Ruff linting, formatting, and import sorting; CI runs both Ruff gates and pytest.
- **Independent QA — PASS (implementation gate)**: Implementation completion explicitly requires a separate non-implementing QA sub-agent to audit coverage and run `ruff check`, `ruff format --check`, and the full pytest suite after remediation.
- **Interoperability — PASS**: FastMCP typed tools and structured outputs use standard MCP semantics. The default transport is stdio, diagnostics use stderr/framework logging, in-memory protocol tests cover discovery/invocation, and a subprocess stdio test plus documented Codex configuration verifies compatibility without Codex-only behavior.
- **Agent ergonomics — PASS**: Drafts have a compact core and four cohesive additive groups (`competition`, `result`, `draft_timing`, `provenance`). Discovery records are already slim and therefore need no field selector; their potentially unbounded collections use 20/100 bounded pages, opaque continuation tokens, focused identity/date/side/result inputs, and concise disambiguation candidates. Successful payloads avoid redundant `status: ok`, empty warning arrays, null errors, and duplicate-input diagnostics.

### Post-design re-check

Phase 1 preserves every gate. The data model makes non-empty diagnostics and their non-OK status explicit while keeping successful payloads sparse; the contracts bound all inputs and outputs; snapshot state exists only because the specification requires stable traversal while upstream collections can change. No constitution exception is required.

## Project Structure

### Documentation (this feature)

```text
specs/001-pro-draft-analysis/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── mcp-tools.md
│   └── response-schemas.md
└── tasks.md                 # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
pyproject.toml
README.md
.env.example
.github/
└── workflows/
    └── quality.yml
src/
└── open_dota_mcp/
    ├── __init__.py
    ├── __main__.py
    ├── config.py
    ├── errors.py
    ├── pagination.py
    ├── server.py
    ├── clients/
    │   ├── __init__.py
    │   └── opendota.py
    ├── models/
    │   ├── __init__.py
    │   ├── common.py
    │   ├── drafts.py
    │   └── discovery.py
    └── services/
        ├── __init__.py
        ├── drafts.py
        ├── identity.py
        └── matches.py
tests/
├── conftest.py
├── fixtures/
│   └── opendota/
├── contract/
│   ├── test_draft_tool.py
│   ├── test_team_tool.py
│   └── test_tournament_tool.py
├── integration/
│   ├── test_discovery_to_draft.py
│   └── test_stdio.py
└── unit/
    ├── test_draft_mapping.py
    ├── test_identity_resolution.py
    ├── test_opendota_client.py
    └── test_pagination.py
```

**Structure Decision**: Use one `src`-layout package. `clients` owns documented HTTP contracts and retry policy, `services` owns domain transformations and query semantics, `models` owns stable structured MCP schemas, and `server.py` is the thin three-tool boundary. This separation isolates upstream schema variation from public contracts without introducing persistence or a generic repository layer.

## Implementation Design

### OpenDota integration

- Use one shared asynchronous `httpx.AsyncClient` with base URL `https://api.opendota.com/api`, explicit connect/read/write/pool timeouts, a descriptive user agent, and optional `Authorization: Bearer` configuration. Never include request headers or full credential-bearing URLs in diagnostics.
- Use `GET /matches/{match_id}`, `/heroes`, `/constants/patch`, `/leagues`, `/leagues/{league_id}/matches`, `/teams?page=N`, `/teams/{team_id}`, `/teams/{team_id}/matches`, and `/proPlayers` only. Ignore unknown fields and reject malformed top-level shapes.
- Fetch per-invocation reference catalogs only when needed. The professional-player catalog is a fallback for a missing match-record professional name; failure to enrich a usable account ID becomes a warning, not loss of the draft.
- Treat upstream collection ordering as unspecified: normalize records, then sort by `(start_time, match_id)` descending. Silently collapse identical upstream records before filtering and snapshot creation, but emit a non-empty warning when records sharing a match ID conflict.

### Draft transformation

- Deduplicate requested match IDs silently in first-occurrence order. Do not expose `duplicates_omitted`, a duplicate count, or a warning; fetch distinct matches with bounded concurrency while preserving result order and producing one outcome per distinct match.
- Verify draft professional eligibility by grouping matches by league ID and confirming membership in the documented `/leagues/{league_id}/matches` professional-only surface. A missing/zero league ID or absence from that surface is `not_professional`; unavailable and unparsed records retain their distinct outcomes.
- If a draft of `n` actions has integer `order` values exactly equal to `0..n-1`, sort by `order` and mark `ordering_quality: authoritative`. Otherwise preserve every upstream array element, retain each supplied order or null, include its `source_index`, and mark `degraded`.
- Map a pick to a player only when exactly one match player has the picked hero ID on the acting side. Use `players[].name`, then the `/proPlayers` name for the same `account_id`, then the Steam32 account ID display fallback. Never use `personaname`. Bans always have `player: null`.
- Compute completeness from required stable IDs/labels and associations. Missing labels stay null, numeric IDs remain, and precise warnings attach to the affected draft/action/team/player record. Serialize `warnings` only when at least one warning exists.

### Identity resolution and filters

- Require exactly one first-page selector: stable ID or nonblank name query. Normalize Unicode with case folding, retain alphanumerics, and collapse punctuation/whitespace.
- Prefer a unique normalized exact league name or team name/tag. Otherwise rank case-insensitive normalized substring candidates by starts-with, earliest match position, shorter normalized label, recency (teams), and stable numeric ID; return at most 10 and never fuzzy-match.
- Team catalog retrieval starts at page 0 and follows documented 1,000-entry pages until a short/empty page, rejecting a repeated page signature as malformed upstream behavior.
- Parse dates strictly as `YYYY-MM-DD`; interpret start as `00:00:00Z` and inclusive end as the next UTC midnight exclusive. Apply date, side, and team-relative result filters with AND semantics. Exclude records where the selected team appears on neither/both sides and attach a collection warning.

### Pagination and errors

- On a first collection call, materialize the fully normalized, filtered, sorted result set in a process-local snapshot keyed by a cryptographically random identifier. Store selector/filter fingerprint, records, page size, creation/expiry time, and next offset for 30 minutes.
- Continuation calls may provide the token alone. If selector/filter/page-size arguments are repeated, they must match the snapshot fingerprint. Rotate the opaque token after each page so replayed or cross-tool tokens are rejected. Remove terminal, expired, superseded, and least-recently-used snapshots; expiration returns restart guidance.
- The snapshot registry is traversal state, not a reusable upstream cache. It has no fixed record ceiling, stores only domain match summaries, and is bounded by expiry plus a small maximum count of concurrent local traversals.
- Successful responses and successful draft items omit generic `status`, empty `warnings`, and `error`. Expected validation, identity, pagination, eligibility, and upstream failures return a non-empty typed `error` whose nested `status` identifies the non-OK outcome alongside code, message, target, retry exhaustion, and `retryable_later`. Ambiguity returns candidates plus a non-empty `warnings` entry with nested `status: needs_selection`. Draft batch record failures remain per-match outcomes with the failure status nested in `error`; fields that have no value for that outcome are omitted rather than serialized as null placeholders. Unexpected exceptions are masked and logged to stderr.

## Complexity Tracking

No constitution violations require justification.
