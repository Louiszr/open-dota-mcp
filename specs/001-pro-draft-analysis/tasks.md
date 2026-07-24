# Tasks: Professional Draft Analysis MCP

**Input**: Design documents from `/specs/001-pro-draft-analysis/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Pytest coverage is required for every public Python function and all three MCP tools. Tests must remain deterministic and offline; retry tests use injected clocks, sleepers, and jitter rather than real delays.

**Organization**: Tasks are grouped by user story so each capability can be implemented and verified as an independent increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it changes a different file and has no dependency on an incomplete task
- **[Story]**: Maps a task to its user story (`US1` through `US4`)
- Every checklist entry names the exact file where the work occurs

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the installable Python package, quality configuration, and deterministic test scaffold.

- [X] T001 Create the Python 3.13 `uv` project metadata, FastMCP/httpx runtime dependencies, pytest/pytest-asyncio development dependencies, package entry point, and Ruff lint/format/import-sorting plus public Google-style docstring enforcement in `pyproject.toml`
- [X] T002 [P] Create the importable package surface and version metadata in `src/open_dota_mcp/__init__.py`
- [X] T003 [P] Create package markers for the client, model, and service layers in `src/open_dota_mcp/clients/__init__.py`, `src/open_dota_mcp/models/__init__.py`, and `src/open_dota_mcp/services/__init__.py`
- [X] T004 [P] Create shared pytest fixtures for deterministic clocks, sleepers, jitter, `httpx.MockTransport`, and FastMCP in-memory clients in `tests/conftest.py`
- [X] T005 [P] Add the offline Ruff and pytest quality workflow using `uv` in `.github/workflows/quality.yml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement the shared configuration, domain diagnostics, OpenDota client, identity resolution, and deterministic traversal machinery required by every tool.

**Critical**: No user-story implementation begins until this phase is complete.

- [X] T006 [P] Write public configuration tests for defaults, explicit retry limits/timeouts, optional `OPENDOTA_API_KEY`, and secret-safe representations in `tests/unit/test_config.py`
- [X] T007 [P] Define typed environment configuration for the OpenDota base URL, optional API key disabled by default, HTTP timeouts, three-attempt retry policy, ten-second delay budget, 30-minute snapshot expiry, and 32-traversal default capacity in `src/open_dota_mcp/config.py`
- [X] T008 [P] Define sparse `DataWarning` and `ToolErrorDetail` models, stable status/error enums, safe serialization, and secret-free exception mapping in `src/open_dota_mcp/errors.py`
- [X] T009 [P] Define shared UTC, team, league, hero, player, page, and sparse diagnostic Pydantic value objects with fully typed public APIs in `src/open_dota_mcp/models/common.py`
- [X] T010 [P] Write deterministic public-client tests for every documented OpenDota GET method, permissive unknown fields, malformed top-level shapes, no authentication by default, optional officially supported Bearer authentication without query credentials, redaction, retryable 429/408/5xx and connection/timeout classification, valid and invalid `Retry-After`, bounded exponential jitter, successful recovery, retry exhaustion, delay-budget/deadline refusal, non-retryable failures, and immediate cancellation in `tests/unit/test_opendota_client.py`
- [X] T011 Implement the typed asynchronous OpenDota client methods for `/matches/{match_id}`, `/heroes`, `/constants/patch`, `/leagues`, `/leagues/{league_id}/matches`, `/teams?page=N`, `/teams/{team_id}`, `/teams/{team_id}/matches`, and `/proPlayers`, using no authentication by default and the documented Bearer header only for a configured key, plus safe finite retries and secret-free errors, in `src/open_dota_mcp/clients/opendota.py`
- [X] T012 [P] Write public identity-resolution tests for Unicode/case/punctuation normalization, unique exact name/tag preference, deterministic ranked substrings, ten-candidate bounds, blank/no-match results, recency tie-breaking, and repeated team-catalog page rejection in `tests/unit/test_identity_resolution.py`
- [X] T013 [P] Implement league and team selector validation, catalog traversal, normalization, exact resolution, and deterministic bounded candidate ranking in `src/open_dota_mcp/services/identity.py`
- [X] T014 [P] Write public pagination tests for 20/100 page bounds, unbounded total traversal, canonical query fingerprints, opaque rotating single-use tokens, snapshot mutation isolation, no repeat/skip, terminal cleanup, mismatch/cross-tool/replay rejection, 30-minute expiry, least-recently-used eviction guidance, and the 32-traversal default capacity in `tests/unit/test_pagination.py`
- [X] T015 [P] Implement the 30-minute process-local traversal snapshot registry, canonical fingerprints, cryptographically opaque rotating tokens, page slicing, terminal cleanup, and expiry/LRU eviction in `src/open_dota_mcp/pagination.py`
- [X] T016 Write public sparse-schema and error-serialization tests covering omission of successful status, empty warnings, absent errors and null outcome placeholders while retaining zero/false domain values in `tests/unit/test_common_models.py`
- [X] T017 Add explicit reusable OpenDota response fixtures for complete, partial, malformed, throttled, unavailable, and conflicting-duplicate records in `tests/fixtures/opendota/shared.json`

**Checkpoint**: Shared infrastructure is tested and ready; all user stories may now proceed.

---

## Phase 3: User Story 1 - Inspect Match Drafts (Priority: P1) MVP

**Goal**: Return compact, ordered professional draft evidence for one to ten requested match IDs with reliable hero, team, patch, and picked-player identity context.

**Independent Test**: Request known complete and partial professional match fixtures and verify first-occurrence batch ordering, every upstream action, authoritative/degraded ordering, localized labels, Steam32-only fallback identity, sparse per-match failures, and all four additive field groups.

### Tests for User Story 1

- [X] T018 [P] [US1] Add at least 20 complete draft fixtures plus missing-label, missing-name, ambiguous-player, degraded-order, unavailable, nonprofessional, unparsed, and malformed variants in `tests/fixtures/opendota/drafts.json`
- [X] T019 [P] [US1] Write risk-based transformation tests for complete/degraded action ordering, source-index retention, unique same-side hero-to-player mapping, professional-name/catalog/Steam32 fallback precedence, persona-name exclusion, bans without players, completeness warnings, timing association, UTC dates, and unknown upstream field omission in `tests/unit/test_draft_mapping.py`
- [X] T020 [P] [US1] Write MCP contract tests for validation and silent de-duplication of 1–10 IDs, preserved request order, mixed per-match outcomes, slim defaults, each additive group and all groups together, invalid group rejection before I/O, sparse diagnostics, partial data, successful retry recovery, `Retry-After`, retry exhaustion, non-retryable failures, and cancellation/deadline propagation in `tests/contract/test_draft_tool.py`

### Implementation for User Story 1

- [X] T021 [P] [US1] Define draft action, timing, competition, result, provenance, match draft, sparse outcome union, and response models matching the published contracts in `src/open_dota_mcp/models/drafts.py`
- [X] T022 [US1] Implement professional eligibility checks, bounded concurrent retrieval, first-occurrence ordering, reference enrichment, draft transformation, player association, degradation/completeness warnings, and additive response-group shaping in `src/open_dota_mcp/services/drafts.py`
- [X] T023 [US1] Register the typed `get_pro_match_drafts` tool with its slim-default, include-group, batch-limit, and error-outcome description in `src/open_dota_mcp/server.py`
- [X] T024 [US1] Verify the complete and partial fixture scenarios meet the draft acceptance contract without network access in `tests/contract/test_draft_tool.py`

**Checkpoint**: User Story 1 is independently usable as the MVP draft-analysis capability.

---

## Phase 4: User Story 2 - Find Recent Tournament Matches (Priority: P2)

**Goal**: Resolve a professional league by ID or name and traverse every eligible match newest first through bounded immutable pages.

**Independent Test**: Resolve known, ambiguous, missing, amateur, empty, and active league fixtures; traverse pages after inserting a newer match and verify stable ordering, complete terminal traversal, no repeat/skip, bounded response records, and actionable token failures.

### Tests for User Story 2

- [X] T025 [P] [US2] Add professional, amateur, ambiguous-name, empty, duplicate/conflicting, partial-label, and newly-mutated tournament fixtures in `tests/fixtures/opendota/tournaments.json`
- [X] T026 [P] [US2] Write MCP contract tests for ID/name selectors, normalized exact and bounded ambiguous resolution, ineligible/no-data outcomes, slim domain records, 20/100 page limits, complete no-ceiling traversal, terminal metadata, immutable snapshots, invalid/mismatched/expired tokens, sparse record warnings, successful retry recovery, `Retry-After`, exhaustion, non-retryable failures, and cancellation/deadline propagation in `tests/contract/test_tournament_tool.py`

### Implementation for User Story 2

- [X] T027 [P] [US2] Define league candidates, tournament match summaries, page metadata, selection outcomes, sparse errors, and tournament response unions in `src/open_dota_mcp/models/discovery.py`
- [X] T028 [US2] Implement league resolution, professional eligibility, deterministic duplicate collapse/conflict warnings, `(start_time, match_id)` newest-first normalization, domain projection, and snapshot-backed tournament paging in `src/open_dota_mcp/services/matches.py`
- [X] T029 [US2] Register the typed `list_pro_tournament_matches` tool with focused selectors, bounded page controls, slim output, continuation semantics, and actionable errors in `src/open_dota_mcp/server.py`
- [X] T030 [US2] Verify tournament name disambiguation, empty terminal pages, and mutation-stable terminal traversal against offline fixtures in `tests/contract/test_tournament_tool.py`

**Checkpoint**: User Story 2 can independently discover all matches for a selected professional tournament.

---

## Phase 5: User Story 3 - Find Recent Team Matches (Priority: P3)

**Goal**: Resolve a professional team by ID, name, or tag and traverse recent matches filtered by inclusive UTC dates, side, and team-relative result.

**Independent Test**: Resolve known and ambiguous team fixtures, exercise each filter and their AND combination, traverse a changing dataset, and verify team-relative summaries, anomaly exclusion, empty results, and terminal metadata.

### Tests for User Story 3

- [X] T031 [P] [US3] Add renamed/reused/ambiguous team identities, filtered histories, no-result cases, anomalous side placement, partial labels/scores, duplicate/conflicting records, and mutation fixtures in `tests/fixtures/opendota/teams.json`
- [X] T032 [P] [US3] Write MCP contract tests for ID/name/tag selectors, catalog traversal and disambiguation, strict/reversed UTC dates, Radiant/Dire and win/loss filters with AND semantics, newest-first slim records, anomalous-side exclusion, 20/100 paging, immutable/terminal/invalid token behavior, empty results, sparse warnings, successful retry recovery, `Retry-After`, exhaustion, non-retryable failures, and cancellation/deadline propagation in `tests/contract/test_team_tool.py`

### Implementation for User Story 3

- [X] T033 [US3] Extend discovery schemas with team candidates, canonical filter echoes, team-relative match summaries, selection outcomes, and team response unions in `src/open_dota_mcp/models/discovery.py`
- [X] T034 [US3] Implement team resolution, strict inclusive UTC date parsing, side/result AND filters, unique-side validation, opponent/result derivation, duplicate normalization, warnings, newest-first sorting, and snapshot-backed team paging in `src/open_dota_mcp/services/matches.py`
- [X] T035 [US3] Register the typed `list_pro_team_matches` tool with focused selectors and filters, bounded pages, slim output, continuation semantics, and actionable errors in `src/open_dota_mcp/server.py`
- [X] T036 [US3] Verify individual/combined filters, valid empty pages, anomalous records, and mutation-stable traversal against offline fixtures in `tests/contract/test_team_tool.py`

**Checkpoint**: User Story 3 can independently discover a selected team's relevant matches with bounded filtering.

---

## Phase 6: User Story 4 - Run as a Local Analysis Service (Priority: P4)

**Goal**: Install, configure, register, discover, and invoke the three-tool server locally through standard stdio MCP without editing source code or exposing credentials.

**Independent Test**: From a clean environment, install the project, inspect exactly three tools, start it over stdio, run a discovery-to-draft fixture journey through a FastMCP client, and confirm stdout remains protocol-only with and without an API key.

### Tests for User Story 4

- [X] T037 [P] [US4] Write an in-memory FastMCP discovery-to-draft integration test that asserts exactly three stable tool names, typed schemas/descriptions, a two-call known-ID flow, a three-call ambiguous-name-to-stable-ID-to-draft flow for both tournament and team discovery, sparse outputs, and framework-level invocation behavior in `tests/integration/test_discovery_to_draft.py`
- [X] T038 [P] [US4] Write a subprocess stdio compatibility test for initialization, tool listing/invocation, protocol-only stdout, stderr diagnostics, clean shutdown, public no-key operation, and API-key redaction in `tests/integration/test_stdio.py`

### Implementation for User Story 4

- [X] T039 [US4] Complete shared FastMCP lifespan/client wiring, dependency injection, masked unexpected-error logging, and exactly-three-tool server construction in `src/open_dota_mcp/server.py`
- [X] T040 [US4] Implement the module entry point that launches the server with stdio as the default transport and writes no banner to stdout in `src/open_dota_mcp/__main__.py`
- [X] T041 [US4] Document the exact `uv pip install -e .` editable-install path, clean `uv` setup, no-key default and optional Bearer-key configuration, startup, Codex registration, all tool inputs/groups/limits, common two/three-call workflows, continuation restart behavior, and troubleshooting in `README.md`

**Checkpoint**: All four user stories work through a locally registered standards-compliant MCP server.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validate contracts, packaging, documentation, security, and quality across the completed feature.

- [X] T042 [P] Add a secret-safe environment template containing only documented non-secret placeholders and retry/runtime configuration in `.env.example`
- [X] T043 Reconcile generated FastMCP input/output schemas, exact tool count, field-group meanings, sparse diagnostics, page metadata, and stable error codes with `specs/001-pro-draft-analysis/contracts/mcp-tools.md` and `specs/001-pro-draft-analysis/contracts/response-schemas.md`
- [X] T044 Run every offline editable-install, inspection, two/three-call end-to-end, snapshot, partial-draft, and retry scenario from `specs/001-pro-draft-analysis/quickstart.md` and record any required corrections in `specs/001-pro-draft-analysis/quickstart.md`
- [X] T045 Audit every public function, class, and MCP tool for complete type signatures and Google-style docstrings, remediate `src/open_dota_mcp/` and verify the configured Ruff documentation rules in `pyproject.toml`
- [X] T046 Run the timed clean-environment `uv pip install -e .` through Codex registration and first successful invocation workflow from `specs/001-pro-draft-analysis/quickstart.md`, require completion in under 10 minutes, and record commands, environment, elapsed time, and result in `specs/001-pro-draft-analysis/qa-report.md`
- [X] T047 Require an independent sub-agent that performed no implementation to audit all public-surface and risk-based tests, verify T045 and T046 evidence, then run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`, with implementation remediation and independent re-runs until all checks pass, recording the final QA result in `specs/001-pro-draft-analysis/qa-report.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 — Setup**: Starts immediately.
- **Phase 2 — Foundational**: Depends on Phase 1 and blocks every user story.
- **Phase 3 — US1**: Depends only on the foundation and provides the suggested MVP.
- **Phase 4 — US2**: Depends only on the foundation; it may be built in parallel with US1.
- **Phase 5 — US3**: Depends only on the foundation at the capability level. If one developer implements both discovery stories, apply US2's additions to shared files before US3's additions.
- **Phase 6 — US4**: Depends on US1, US2, and US3 because it verifies the integrated exactly-three-tool service.
- **Phase 7 — Polish**: Depends on every story selected for delivery; T047 is always last.

### User Story Dependency Graph

```text
Setup -> Foundation -> US1 (P1) ----\
                    -> US2 (P2) -----+-> US4 (P4) -> Polish -> Independent QA
                    -> US3 (P3) ----/
```

### Within Each User Story

1. Add deterministic fixtures and required public/contract tests before or alongside implementation.
2. Define or extend stable domain models before service transformations.
3. Implement service behavior before registering its thin MCP tool boundary.
4. Run the story checkpoint tests before treating the story as complete.

## Parallel Opportunities

- T002–T005 can proceed in parallel after T001 establishes project conventions.
- T006–T010, T012–T015, and T017 touch separate foundational files and can proceed in parallel; T011 follows its tests and T016 validates the resulting shared schemas.
- After Phase 2, US1, US2, and US3 can be assigned concurrently, with coordination for the shared `models/discovery.py`, `services/matches.py`, and `server.py` integration points.
- Within each story, fixture and test authoring marked `[P]` can proceed concurrently with model work marked `[P]`.
- T037 and T038 can proceed in parallel once all three tool contracts exist; T042 can proceed alongside integrated documentation validation.

## Parallel Examples

### User Story 1

```text
Task T018: Create comprehensive draft fixtures in tests/fixtures/opendota/drafts.json
Task T019: Write draft transformation tests in tests/unit/test_draft_mapping.py
Task T020: Write draft MCP contract tests in tests/contract/test_draft_tool.py
Task T021: Define draft response models in src/open_dota_mcp/models/drafts.py
```

### User Story 2

```text
Task T025: Create tournament fixtures in tests/fixtures/opendota/tournaments.json
Task T026: Write tournament MCP contract tests in tests/contract/test_tournament_tool.py
Task T027: Define tournament discovery models in src/open_dota_mcp/models/discovery.py
```

### User Story 3

```text
Task T031: Create team fixtures in tests/fixtures/opendota/teams.json
Task T032: Write team MCP contract tests in tests/contract/test_team_tool.py
```

### User Story 4

```text
Task T037: Write in-memory integration coverage in tests/integration/test_discovery_to_draft.py
Task T038: Write stdio subprocess coverage in tests/integration/test_stdio.py
```

## Implementation Strategy

### MVP First

1. Complete Setup and Foundational phases.
2. Complete US1, including its tests and checkpoint.
3. Stop and validate the ordered-draft capability independently before adding discovery.

### Incremental Delivery

1. Deliver US1 for direct match-ID draft inspection.
2. Add US2 for tournament-scoped match discovery.
3. Add US3 for filtered team-scoped match discovery.
4. Complete US4 to package and validate the integrated local MCP experience.
5. Finish cross-cutting contract reconciliation, timed acceptance, and independent QA.

## Notes

- `[P]` means the task can run without editing a file owned by another incomplete task.
- Unknown OpenDota fields remain isolated at the client boundary and never leak into public responses.
- Discovery records use a bounded fixed slim projection; draft records use only the four documented additive groups.
- Every automated test remains offline and uses no real retry sleeps.
- Commit after each task or coherent task group, and do not mark T047 complete until the independent QA sub-agent passes every gate.
