# Implementation Plan: Reliable Retries and Lean Team Drafting Report

**Branch**: `003-draft-analysis-retries` | **Date**: 2026-07-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-draft-analysis-retries/spec.md`

## Summary

Harden safe OpenDota GETs with a six-attempt, monotonic, cancellation-safe retry policy that honors
usable `Retry-After` guidance without permitting immediate retry loops. Add one read-only
`analyze_pro_team_drafts` MCP tool that examines a bounded recent-match quota, applies patch,
tournament, side, result, and first-ban filters from the selected team's perspective, and returns
only eligible matches. The default response contains a compact team/filter/coverage envelope and a
minimal match core. Five optional groups add supported draft, lane, gold, structure, and objective
facts. Internal filtering, provenance, and diagnostics never inflate the public schema.

## Technical Context

**Language/Version**: Python 3.13+

**Primary Dependencies**: FastMCP, httpx, Pydantic (through FastMCP), `regex` for timeout-bounded
full-string patch expressions, and Python standard-library asyncio, datetime/email parsing,
logging, random, and enum/collection utilities

**Storage**: Existing per-user SQLite upstream-response cache and bounded process-local immutable
pagination snapshots. No new durable domain storage.

**Testing**: pytest and pytest-asyncio with `httpx.MockTransport`, injectable clocks/jitter/sleepers,
temporary SQLite stores, fixture-rich service tests, FastMCP contract tests, and stdio integration
tests

**Target Platform**: Local macOS or Linux process launched by Codex or another MCP client over
stdio

**Project Type**: Single Python package providing a local read-only MCP service and cache CLI

**Performance Goals**: Inspect no more than 100 completed matches per first page; bound match-detail
concurrency to 5; return no more than 25 eligible matches per page; perform no upstream I/O for
valid cache hits or continuations; coordinate equivalent cache misses into one retry sequence

**Constraints**: Six total attempts; fallback bases 2/4/8/16/32 seconds with additive 0-20%
jitter; 40-second individual-delay, 75-second cumulative-delay, and 90-second elapsed defaults;
lookback 1-100 (default 25); page size 1-25 (default 10); regex at most 64 characters and timeout
bounded; Tier 1 is `premium`; protocol-only stdout; offline deterministic tests

**Scale/Scope**: Existing nine OpenDota GET operations and three tools, plus one report tool; one
resolved team, at most 100 match-detail records, five optional groups, and at most 32 concurrent
30-minute process-local traversals

## Constitution Check

*GATE: Passed before Phase 0 and re-checked after Phase 1.*

- **Scope — PASS**: One demonstrated report and shared retry hardening are added. Existing caches,
  lookup identities, and snapshots are reused; no recommendation engine, new authentication,
  remote persistence, or raw-field selector is introduced.
- **OpenDota contract — PASS**: `research.md` verifies all consumed endpoints and field meanings.
  Safe retries are bounded, honor valid standard guidance, and propagate cancellation.
- **Testing — PASS**: Public retry, validation, model, service, MCP, and pagination behavior receives
  pytest coverage. Risk tests cover guidance parsing, budgets, cache ownership, lookback ordering,
  filters, chronology, supported checkpoint lookup, attribution, sparse data, and pagination.
- **Quality — PASS**: Public APIs are typed and Google-documented. Secrets and raw bodies remain out
  of logs and all changes remain subject to Ruff check and format gates.
- **Independent QA — PASS (implementation gate)**: `/speckit-implement` must use a separate
  non-implementing QA sub-agent to audit tests and run Ruff check, Ruff format check, and pytest.
- **Interoperability — PASS**: Typed FastMCP inputs/results, standard read-only annotations,
  protocol-only stdout, and Codex-compatible subprocess tests remain required.
- **Agent ergonomics — PASS**: The default response is lean, groups are cohesive, eligible matches
  are paginated, and focused filters prevent client-side bulk processing. Public responses omit
  team tags, unlikely lookup IDs, request echoes, intermediate filter accounting, provenance,
  diagnostic wrappers, and unsupported-data explanations.

### Post-design re-check

Phase 1 preserves every gate. The contract retains team and match IDs only where follow-up tool
calls benefit, represents heroes as names, and projects internal normalized records into a small
stable public model. Sparse `null`/omission handles missing supported evidence without broad
availability or warning objects. No constitution exception is required.

## Project Structure

### Documentation (this feature)

```text
specs/003-draft-analysis-retries/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── mcp-tool.md
│   └── response-schema.md
└── tasks.md                     # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
pyproject.toml                    # Add timeout-capable regex dependency
.env.example                     # Document revised retry settings
README.md                         # Document report tool, groups, filters, pages, and retries
src/open_dota_mcp/
├── clients/opendota.py          # Retry policy and existing cache boundary
├── models/analysis.py           # Lean public report and internal normalized models
├── services/analysis.py         # Selection, filtering, shaping, checkpoints, evidence
├── services/drafts.py           # Reuse identity/action mapping rules
├── services/identity.py         # Existing stable identity helpers
├── services/matches.py          # Existing discovery remains compatible
├── cache/store.py               # Existing single-owner population behavior
├── config.py                    # Retry defaults
├── errors.py                    # Concise public errors; detailed internal diagnostics
├── pagination.py                # Reused immutable traversal registry
└── server.py                    # Register analyze_pro_team_drafts
tests/
├── fixtures/opendota/analysis.json
├── unit/
│   ├── test_opendota_client.py
│   ├── test_analysis_mapping.py
│   ├── test_analysis_models.py
│   └── test_config.py
├── contract/test_analysis_tool.py
└── integration/
    ├── test_analysis_journey.py
    ├── test_cache_multiprocess.py
    └── test_stdio.py
```

**Structure Decision**: Keep the existing single `src`-layout package. Retry behavior stays at the
HTTP/cache boundary. A focused analysis service owns orchestration and an explicit projection step
separates rich internal normalization from the lean MCP response.

## Implementation Design

### Retry decisions and exhaustion

- Add settings for `max_attempts=6`, `retry_delay_cap=40`, `retry_delay_budget=75`, and
  `retry_elapsed_budget=90`; retain injectable monotonic/wall clocks, sleeper, and jitter.
- For retries 1-5, calculate base delays 2/4/8/16/32 and additive jitter in `[0, base*0.2]`.
- Parse `Retry-After` as positive finite seconds or a future HTTP date. Wait for the greater of
  usable upstream guidance and the safe fallback; invalid/short guidance cannot create a tight loop.
- Before sleeping, enforce attempt, individual delay, accumulated delay, elapsed, caller deadline,
  and cancellation limits. Retry safe GET failures only.
- Keep detailed failure class, attempt, delay source/value, and budget observations in structured
  stderr logging. A public exhausted error contains only code/message, actionable reason, and an
  optional safe retry delay.
- Cache hits bypass retry; only the cache population owner runs the retry state machine.

### Report selection pipeline

1. Validate team ID, lookback, tier list, scenario enums, include groups, page size, and version
   expression before match-detail retrieval. Continuations use the saved normalized fingerprint.
2. Resolve the team and cached patch/league/hero/player references. Without a caller expression,
   select the latest valid patch by release date and retain only its label for the public filter.
3. Fetch team matches, normalize completed records, deduplicate, sort newest first, and take the
   bounded lookback. Never backfill an unparsed or filtered slot from older history.
4. Fetch detail records with concurrency 5. Internal records may retain source information needed
   to resolve conflicts, but public models never serialize it.
5. Determine team placement, parse status, patch label, tier, side/result, and ban order; apply all
   filters with AND semantics. Keep detailed evaluation state internal.
6. Compute only examined/parsed/unparsed public coverage. Materialize eligible
   matches and requested groups, snapshot them, then paginate. Empty eligibility is successful.

### Public response projection

- Envelope: `team`, `filters`, `coverage`, `matches`, and optional `next_cursor`; coverage contains
  only examined, parsed, and unparsed counts.
- Core match: match ID, start time, duration, tournament name/tier, patch label, analyzed-team name,
  opponent ID/name, side, result, and nullable ban order.
- Explicitly exclude team tags; league, patch, hero, action-source, and account IDs; catalog/source
  metadata; request echoes; per-stage/filter results; warning/reason arrays; and generic quality,
  availability, completeness, analysis, or parse statuses.
- Unparsed, filtered, malformed, and failed-detail matches contribute to aggregate coverage but do
  not become public outcome records.

### Optional groups

- `draft`: one chronological order, action type, per-team type round, acting-team name, hero name,
  optional player name, and compact optional matchup knowledge. Heroes are strings. Derive round
  without a patch schedule by taking each team's ordered action subsequence, grouping consecutive
  equal types, and numbering pick runs and ban runs independently from 1.
- `lanes`: lane name, analyzed-team/opponent hero-name lists, and nullable analyzed-team XP and
  last-hit differences at 10 minutes.
- `economy`: nullable analyzed-team gold differences and per-hero total gold at 10/20 minutes from
  `radiant_gold_adv` and `gold_t`. The public name remains gold because OpenDota parses `gold_t`
  from total earned gold rather than its separately observed net-worth value.
- `structures`: cumulative compact structure-key lists lost by each team through 10/20 minutes;
  `[]` is verified none and `null` is unavailable. No zero-filled counter trees or totals.
- `objectives`: attributable Roshan/Tormentor event-time lists through 25 minutes; `[]` is verified
  zero and `null` is unavailable/not applicable. Counts and first-take fields are not duplicated.
- Internal attribution failures and sampling details are tested and logged where appropriate but
  are not public response fields.

### Pagination and compatibility

- Reuse opaque, rotating, single-use 30-minute snapshot tokens bound to all first-page arguments.
- Repeat only team, filters, and compact coverage on every page. Emit `next_cursor` only when more
  eligible matches remain.
- Existing tool names and schemas remain compatible. The server instruction changes from exactly
  three to four read-only capabilities.

## Complexity Tracking

No constitution violations require justification.
