# Tasks: Reliable Retries and Lean Team Drafting Report

**Input**: Design documents from `/specs/003-draft-analysis-retries/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Pytest coverage is required for every public-facing Python function and MCP tool. Retry, normalization, filtering, evidence attribution, and pagination receive risk-based internal coverage because they contain complex branching and failure recovery.

**Organization**: Tasks are grouped by user story so each increment can be implemented and tested independently after the shared foundation is complete.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it changes a different file and has no dependency on an incomplete task
- **[Story]**: Maps the task to a user story in `spec.md`
- Every checklist item names the exact file or files it changes or validates

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the feature dependency and deterministic source data used throughout implementation.

- [X] T001 Add the timeout-capable `regex` runtime dependency and lock it with uv in `pyproject.toml` and `uv.lock`
- [X] T002 [P] Create explicit multi-patch, multi-tier, parsed/unparsed, draft, timeline, structure, and objective fixtures in `tests/fixtures/opendota/analysis.json`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared public errors and report models used by retry handling and every report story.

**⚠️ CRITICAL**: Complete this phase before beginning any user-story implementation.

- [X] T003 [P] Add public-model tests for retry exhaustion details, sparse report serialization, coverage invariants, enum validation, and prohibited fields in `tests/unit/test_analysis_models.py`
- [X] T004 Extend structured errors with exhaustion reason, optional safe retry delay, and concise analysis validation responses without exposing raw guidance or diagnostics in `src/open_dota_mcp/errors.py`
- [X] T005 Implement typed sparse request, envelope, core-match, filter, coverage, and optional evidence models from the data model in `src/open_dota_mcp/models/analysis.py`
- [X] T006 Export the new public analysis model surface without changing existing model contracts in `src/open_dota_mcp/models/__init__.py`

**Checkpoint**: Shared error and model contracts are ready for all four stories.

---

## Phase 3: User Story 1 - Recover Safely From Rate Limits (Priority: P1) 🎯 MVP

**Goal**: Make every repeatable OpenDota GET recover from transient failures through finite, monotonic, cancellation-safe retries and return an actionable bounded exhaustion result.

**Independent Test**: With injected clocks, jitter, sleepers, and mocked HTTP, cover missing, blank, zero, negative, malformed, non-finite, expired, short, valid, date-form, and excessive `Retry-After`; all retryable classes; recovery; every budget; cancellation; non-retryable failures; cache hits; and shared cache-population ownership without real waiting or network traffic.

### Tests for User Story 1

- [X] T007 [P] [US1] Update public `Settings.from_env()` and `Settings.validate()` tests for six attempts, 2/4/8/16/32 bases, 20% jitter, 40-second delay cap, 75-second accumulated budget, 90-second elapsed budget, finite validation, and secret-safe representations in `tests/unit/test_config.py`
- [X] T008 [P] [US1] Add deterministic client tests for all retryable status/network classes, `Retry-After` validity classes, repeated short guidance, additive jitter bounds, safe-method classification, recovery, attempt/delay/elapsed/deadline exhaustion, cancellation during request or sleep, sanitized logging, and no extra request in `tests/unit/test_opendota_client.py`
- [X] T009 [P] [US1] Add tool-boundary recovery, structured exhaustion, cancellation, and non-retryable regression tests for all existing MCP tools in `tests/contract/test_team_tool.py`, `tests/contract/test_tournament_tool.py`, and `tests/contract/test_draft_tool.py`
- [X] T010 [P] [US1] Extend cache coordination tests for cache-hit bypass, one retry sequence per concurrent population, shared recovery/exhaustion, and waiter cancellation in `tests/integration/test_cache_multiprocess.py`

### Implementation for User Story 1

- [X] T011 [US1] Replace legacy retry settings with validated six-attempt, base-sequence, jitter, individual-delay, accumulated-delay, and elapsed-time defaults and environment variables in `src/open_dota_mcp/config.py`
- [X] T012 [US1] Implement standards-compliant seconds/date `Retry-After` parsing, retryable safe-GET classification, bounded additive jitter, monotonic elapsed accounting, caller-deadline checks, prompt cancellation, structured exhaustion, and secret-safe diagnostics inside the cache population owner in `src/open_dota_mcp/clients/opendota.py`
- [X] T013 [US1] Update retry configuration examples for the revised finite budgets in `.env.example`
- [X] T014 [US1] Run the focused retry and cache tests and resolve regressions in `tests/unit/test_config.py`, `tests/unit/test_opendota_client.py`, and `tests/integration/test_cache_multiprocess.py`

**Checkpoint**: All current read-only OpenDota operations safely recover or stop at a precise bound.

---

## Phase 4: User Story 2 - Generate a Focused Team Drafting Report (Priority: P2)

**Goal**: Add `analyze_pro_team_drafts` with stable-team lookup, newest-first quota selection, latest-patch and tournament-tier filtering, aggregate parse coverage, a lean default response, and immutable bounded pagination.

**Independent Test**: Against fixtures spanning patches, release dates, tiers, parse states, and failures, verify the default latest dated catalog label and `[premium]`, regex/tier overrides, the completed-match quota before filters, stable identity, sparse core output, empty success, validation guidance, newest-first pages, cursor invariants, and at most five concurrent detail reads.

### Tests for User Story 2

- [X] T015 [P] [US2] Add risk-based unit tests for request validation; malformed, 64-character-boundary, full-string, and 50-millisecond-timeout patch expressions; no detail retrieval after expression rejection; latest dated patch selection; completed-match normalization/deduplication/quota; failed or malformed details counting as unparsed while preserving `parsed + unparsed = examined`; core projection; sparse failures; and five-request concurrency in `tests/unit/test_analysis_mapping.py`
- [X] T016 [P] [US2] Add MCP contract tests for public input schema and descriptions, slim defaults including opponent ID, valid patch/tier choices, `invalid_version_expression` correction guidance without engine diagnostics, all validation error codes, prohibited response fields, empty results, page sizes 1/10/25, terminal pages, and opaque cursor replay/mismatch/expiry behavior in `tests/contract/test_analysis_tool.py`
- [X] T017 [P] [US2] Add an offline end-to-end first-page and continuation journey that verifies no continuation I/O and unchanged team/filter/coverage context in `tests/integration/test_analysis_journey.py`

### Implementation for User Story 2

- [X] T018 [US2] Implement public request normalization and validation for team ID, 1-100 lookback, tier lists, include groups, page size, and continuation fingerprints; apply a 50-millisecond timeout to every full-string patch-expression evaluation; and map malformed or timed-out expressions to `invalid_version_expression` without engine diagnostics in `src/open_dota_mcp/services/analysis.py`
- [X] T019 [US2] Implement team resolution, reference loading, latest-patch-by-release-date selection, completed-match quota selection, bounded detail retrieval, aggregate parsed/unparsed coverage with missing, malformed, or failed details counted as unparsed, AND filtering, partial-failure isolation, and lean core projection including opponent ID in `src/open_dota_mcp/services/analysis.py`
- [X] T020 [US2] Extend immutable snapshot traversal to retain the report envelope, enforce a 25-item analysis page maximum, rotate single-use request-bound cursors, and expose only `next_cursor` in `src/open_dota_mcp/pagination.py`
- [X] T021 [US2] Register the typed read-only `analyze_pro_team_drafts` tool with its documented slim default, tier/patch semantics, quota, groups, pagination, sparse-data, and bounded-exhaustion guidance in `src/open_dota_mcp/server.py`
- [X] T022 [US2] Export the analysis service through the package service surface in `src/open_dota_mcp/services/__init__.py`
- [X] T023 [US2] Run and pass default-selection, validation, empty-result, pagination, and journey tests in `tests/unit/test_analysis_mapping.py`, `tests/contract/test_analysis_tool.py`, and `tests/integration/test_analysis_journey.py`

**Checkpoint**: The fourth MCP tool returns a complete, independently usable lean drafting report with deterministic pagination.

---

## Phase 5: User Story 3 - Compare Drafts Under Specific Conditions (Priority: P3)

**Goal**: Narrow reports using team-relative side, result, and authoritative first-ban filters combined with AND semantics.

**Independent Test**: Exercise each filter alone and together for Radiant/Dire wins/losses and first/second/unknown ban order, including matches where the team occurs on neither or both sides; every outcome must satisfy all supplied filters without guessed or public diagnostic state.

### Tests for User Story 3

- [X] T024 [P] [US3] Add mapping tests for team placement, team-relative side/result, authoritative earliest-ban order, unknown chronology, anomalous team membership, and combined-filter truth tables in `tests/unit/test_analysis_mapping.py`
- [X] T025 [P] [US3] Add public tool tests for each scenario filter, AND combinations, invalid values, unknown-value exclusion, and the absence of filter evaluations or exclusion reasons in `tests/contract/test_analysis_tool.py`

### Implementation for User Story 3

- [X] T026 [US3] Implement selected-team placement, side/result transformation, authoritative first-ban derivation, unknown handling, and conjunctive scenario filtering in `src/open_dota_mcp/services/analysis.py`
- [X] T027 [US3] Run and pass the complete scenario-filter acceptance matrix in `tests/unit/test_analysis_mapping.py` and `tests/contract/test_analysis_tool.py`

**Checkpoint**: Agents can compare exactly the desired team-relative competitive conditions without client-side filtering.

---

## Phase 6: User Story 4 - Compare Draft and Game-State Evidence (Priority: P4)

**Goal**: Add independently selectable `draft`, `lanes`, `economy`, `structures`, and `objectives` evidence while preserving one team perspective, sparse missing data, and bounded pages.

**Independent Test**: Request every group separately and together for complete and incomplete fixtures; verify draft chronology/rounds/player/matchup knowledge, lane and economy checkpoints, structure and objective attribution, team-relative symmetry, null-versus-empty semantics, group validation, and unchanged order across maximum-size pages.

### Tests for User Story 4

- [X] T028 [P] [US4] Add risk-based mapping tests for per-team draft rounds, unique player association, matchup knowledge, aligned at-or-before checkpoint lookup, team-relative lane/economy differences, compact structures, attributable objectives, Tormentor applicability, and incomplete/ambiguous evidence in `tests/unit/test_analysis_mapping.py`
- [X] T029 [P] [US4] Extend public model tests for each independently additive evidence group, all-groups serialization, nullable checkpoints, verified empty collections, and exclusion of IDs/provenance/quality/reason wrappers in `tests/unit/test_analysis_models.py`
- [X] T030 [P] [US4] Add MCP contract tests for the slim default, every supported group, all groups together, duplicate/invalid selections, 25-item pages, terminal continuation, stable newest-first perspective, and contract-document examples in `tests/contract/test_analysis_tool.py`

### Implementation for User Story 4

- [X] T031 [P] [US4] Add reusable authoritative chronology, per-team pick/ban round, unique player identity, and hero-to-lane matchup helpers without altering the existing draft tool contract in `src/open_dota_mcp/services/drafts.py`
- [X] T032 [US4] Implement draft evidence projection and safe omission for ambiguous action order, player mapping, lane composition, or matchup knowledge in `src/open_dota_mcp/services/analysis.py`
- [X] T033 [US4] Implement latest-at-or-before sampling plus analyzed-team lane XP/last-hit differences, gold advantages, and per-hero total-gold observations at 10/20 minutes in `src/open_dota_mcp/services/analysis.py`
- [X] T034 [US4] Implement timestamp-attributed compact structure-loss ledgers at 10/20 minutes and Roshan/Tormentor event-time ledgers through 25 minutes with correct null/empty semantics in `src/open_dota_mcp/services/analysis.py`
- [X] T035 [US4] Wire requested groups additively into immutable match projections without computing or serializing unrequested groups in `src/open_dota_mcp/services/analysis.py`
- [X] T036 [US4] Run and pass the complete evidence mapping, model, contract, and maximum-page acceptance suite in `tests/unit/test_analysis_mapping.py`, `tests/unit/test_analysis_models.py`, and `tests/contract/test_analysis_tool.py`

**Checkpoint**: Every requested evidence group is accurate, sparse, independently selectable, and agent-context bounded.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Synchronize documentation, prove MCP interoperability, and complete the independent quality gate.

- [X] T037 [P] Document `analyze_pro_team_drafts`, its focused inputs, slim default, five groups, pagination, aggregate coverage, tier choices, patch matching, checkpoint semantics, sparse evidence, retry bounds, and lookup workflow in `README.md`
- [X] T038 [P] Update the Codex-compatible stdio integration to list exactly four read-only tools, invoke the report, follow its cursor, keep stdout protocol-only, and keep diagnostics on stderr in `tests/integration/test_stdio.py`
- [X] T039 Validate every automated scenario and command in the completed feature guide and correct discrepancies in `specs/003-draft-analysis-retries/quickstart.md`
- [X] T040 Reconcile the live tool schema and serialized response/error examples against `specs/003-draft-analysis-retries/contracts/mcp-tool.md` and `specs/003-draft-analysis-retries/contracts/response-schema.md`
- [X] T041 Run the complete regression suite and resolve compatibility failures across `tests/contract/`, `tests/unit/`, and `tests/integration/`
- [X] T042 Require an independent sub-agent that performed no implementation to audit public-surface and risk-based tests, run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`, require remediation and re-run on any failure, and record the passing result in `specs/003-draft-analysis-retries/tasks.md`
  - Independent QA `/root/independent_qa` initially found a parse-coverage discrepancy and missing risk matrices; remediation was completed and independently re-reviewed.
  - Final QA result: required public/risk-based coverage complete; `uv run ruff check .` exit 0; `uv run ruff format --check .` exit 0 (88 files); `uv run pytest` exit 0 (202 passed, 1 skipped, 20 warnings).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; T001 and T002 may proceed independently.
- **Foundational (Phase 2)**: Depends on Setup and blocks all user-story implementation.
- **US1 (Phase 3)**: Depends on Foundational and establishes reliable upstream reads for report workflows.
- **US2 (Phase 4)**: Depends on Foundational and functionally depends on US1 for resilient multi-read orchestration.
- **US3 (Phase 5)**: Depends on the US2 request, selection, and projection pipeline.
- **US4 (Phase 6)**: Depends on the US2 pipeline; its draft helpers may begin independently of US3, but final report integration uses both.
- **Polish (Phase 7)**: Depends on all stories selected for delivery; T042 is the terminal implementation gate.

### User Story Dependency Graph

```text
Setup -> Foundation -> US1 -> US2 -> US3
                             └-----> US4
US3 + US4 -> Polish -> Independent QA
```

### Within Each User Story

- Write public-surface and warranted internal tests before or alongside implementation.
- Implement validation and models before orchestration and projection.
- Complete core selection before optional evidence.
- Materialize a stable result set before slicing pages.
- Run the story's focused acceptance suite before advancing its checkpoint.

## Parallel Opportunities

- T001 and T002 can run in parallel.
- T003 can be prepared while T004 and T005 are implemented alongside it; T006 follows T005.
- US1 test tasks T007-T010 target separate test surfaces and can run in parallel before T011-T012.
- US2 test tasks T015-T017 can run in parallel; after the selection contract stabilizes, T020 can proceed independently from the service implementation in T018-T019.
- US3 test tasks T024-T025 can run in parallel.
- US4 test tasks T028-T030 and draft-helper task T031 target separate files and can run in parallel before T032-T035 converge in `services/analysis.py`.
- Documentation T037 and stdio coverage T038 can run in parallel after the public contract stabilizes.

## Parallel Example: User Story 1

```text
Task T007: Update public retry configuration tests in tests/unit/test_config.py
Task T008: Add deterministic retry state-machine tests in tests/unit/test_opendota_client.py
Task T010: Add cache-owner coordination tests in tests/integration/test_cache_multiprocess.py
```

## Parallel Example: User Story 2

```text
Task T015: Add selection and validation unit tests in tests/unit/test_analysis_mapping.py
Task T016: Add live MCP schema and lean-response tests in tests/contract/test_analysis_tool.py
Task T017: Add first-page/continuation integration tests in tests/integration/test_analysis_journey.py
```

## Parallel Example: User Story 3

```text
Task T024: Add internal transformation truth-table tests in tests/unit/test_analysis_mapping.py
Task T025: Add public scenario-filter contract tests in tests/contract/test_analysis_tool.py
```

## Parallel Example: User Story 4

```text
Task T028: Add evidence mapping tests in tests/unit/test_analysis_mapping.py
Task T029: Add sparse evidence model tests in tests/unit/test_analysis_models.py
Task T030: Add evidence-group MCP contract tests in tests/contract/test_analysis_tool.py
Task T031: Add reusable chronology and matchup helpers in src/open_dota_mcp/services/drafts.py
```

## Implementation Strategy

### MVP First: Reliable Retry Foundation

1. Complete Setup and Foundational phases.
2. Complete US1 and its focused tests.
3. Stop and validate that existing tools recover safely from minute-rate limits without an extra request or unbounded wait.

US1 is the technical MVP because every report call fans out across several upstream reads. The first user-facing report increment is Setup + Foundation + US1 + US2.

### Incremental Delivery

1. Deliver US1: bounded retry recovery for every current OpenDota GET.
2. Deliver US2: one-call lean team report, default selection, coverage, and pagination.
3. Deliver US3: focused team-relative scenario comparisons.
4. Deliver US4: opt-in draft and game-state evidence.
5. Complete documentation, interoperability checks, full regression, and independent QA.

## Notes

- `[P]` tasks touch different files or can be authored independently before integration.
- User-story labels provide direct traceability to `spec.md` acceptance scenarios.
- Automated tests remain offline, deterministic, and free of real sleeps and API keys.
- Public output must remain smaller than internal normalized state and must not leak filtering or evidence diagnostics.
- T042 cannot pass until all required tests and all three quality commands pass under an independent non-implementing sub-agent.
