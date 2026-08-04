# Tasks: TI 2026 Fantasy Analysis

**Input**: Design documents from `/specs/004-ti-2026-fantasy/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, and `quickstart.md`

**Tests**: Pytest coverage is required for every new public model/helper, both MCP tools, and the MCP resource. Risk-based tests cover API retries, provenance filtering, bounded collection, null/zero/false semantics, position inference, formula parity, and partial failures.

**Organization**: Tasks are grouped by user story so each story remains independently implementable and testable. User Story 4 follows User Story 1 because both are P1 and US1 appears first in the specification.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel after its phase prerequisites are complete because it changes different files and does not depend on another incomplete task
- **[Story]**: Maps a task to its user story (`US1`, `US2`, `US3`, or `US4`)
- Every task names the exact file or files it changes

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish explicit deterministic data for all planned offline tests.

- [X] T001 Create an explicit fixture set containing at least 30 eligible professional maps across at least three series, two patches, and all three tournament tiers, plus separate public, malformed, unparsed, contradictory-provenance, lineup-history, null/zero, Tormentor-attribution, and partial-failure records, and assert the professional-map denominator before outcome tests, in tests/fixtures/opendota/fantasy.json and tests/conftest.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the shared OpenDota operations and cache behavior needed by both P1 tools.

**Critical**: Complete this phase before starting any user-story implementation.

- [X] T002 [P] Add deterministic client tests for player-match history and team-player reads, query forwarding, cache use, safe retry classification, successful recovery, non-retryable failures, bounded increasing backoff with jitter, valid/invalid/over-budget `Retry-After`, cancellation, and retry exhaustion without real delays in tests/unit/test_opendota_client.py
- [X] T003 [P] Add cache identity, allowlist, and freshness tests for player history and team-player operations, including secret exclusion, in tests/unit/test_cache_identity.py and tests/unit/test_cache_policy.py
- [X] T004 [P] Implement typed player-match history and team-player safe GET operations using the existing finite retry/deadline boundary in src/open_dota_mcp/clients/opendota.py
- [X] T005 [P] Add player-history and team-player operation identities and allowlisting without key material in src/open_dota_mcp/cache/identity.py and src/open_dota_mcp/cache/store.py
- [X] T006 [P] Add freshness classifications for player-history and team-player responses in src/open_dota_mcp/cache/policy.py

**Checkpoint**: Focused history and membership reads are deterministic, cached, retry-safe, and ready for story work.

---

## Phase 3: User Story 1 - Review a Player's Fantasy Evidence (Priority: P1) MVP

**Goal**: Resolve one professional player and return a bounded newest-first collection of league-verified professional maps with compact context, all 18 nullable raw fantasy inputs, and optional raw scoring.

**Independent Test**: Request fixtures across public and professional histories, patches, inclusive UTC dates, tiers, heroes, opponents, and known/null series; verify mandatory professional provenance, AND filtering, post-filter limits, compact defaults, exact raw values, scoring opt-in, sparse warnings, and successful empty results.

### Tests for User Story 1

- [X] T007 [P] [US1] Add public request/response model and canonical 18-formula tests covering validation, serialization, numeric floors, fractional values, nonfinite rejection, and null/zero/false distinctions in tests/unit/test_fantasy_models.py
- [X] T008 [P] [US1] Add risk-based mapping tests for compact context, team-relative result/score, direct fields, Smoke uses, participation, First Blood, unavailable proxy rejection, and unique team-consistent Tormentor event attribution in tests/unit/test_fantasy_mapping.py
- [X] T009 [P] [US1] Add professional-player ID/name resolution tests for Unicode NFKC normalization, case folding, punctuation/whitespace-run normalization, normalized-empty input, exact collisions, deterministic name/account-ID ordering, ten-candidate bounds, no-match input, and no detail reads before selection in tests/unit/test_identity_resolution.py
- [X] T010 [P] [US1] Add MCP contract tests for the slim default, `fantasy_scoring` opt-in, invalid group choices, 1/20/100 count bounds, focused filters, latest-patch default, no public-match bypass, professional-provenance rejection before all filters, exact 500-history-record and 200-hydrated-detail boundaries, early completion, exhaustion, limit-specific truncation metadata, partial failures, retry exhaustion, and tool description/annotations in tests/contract/test_fantasy_tool.py
- [X] T011 [P] [US1] Add an offline end-to-end player journey covering ID and two-call name resolution, newest-first post-filter collection, successful empty results, scoring opt-in, and sanitized failures in tests/integration/test_fantasy_journey.py

### Implementation for User Story 1

- [X] T012 [US1] Implement fully typed and Google-documented fantasy request, identity, filter, coverage, context, raw-stat, score, warning, and response models with strict input bounds, 500-history/200-detail coverage bounds, limit-specific terminal reasons, and include validation in src/open_dota_mcp/models/fantasy.py
- [X] T013 [US1] Define typed canonical keys, colors, raw inputs, four formula operations, parameters, safe numeric evaluation, and canonical ordering for all 18 emblems in src/open_dota_mcp/fantasy_rules.py
- [X] T014 [US1] Implement professional-player resolution by positive account ID or exact Unicode NFKC/casefold/punctuation-and-whitespace normalized name, rejecting normalized-empty queries and ordering bounded candidates by normalized name then account ID, in src/open_dota_mcp/services/identity.py
- [X] T015 [US1] Implement player-relative context and raw-stat mapping with explicit null/zero/false semantics, series non-inference, unavailable-stat warning deduplication, and Tormentor attribution in src/open_dota_mcp/services/fantasy.py
- [X] T016 [US1] Implement newest-first traversal in pages of at most 100 records with fixed 500-history-record and 200-unique-detail budgets, detail deduplication and concurrency of five, affirmative league-provenance gating before caller filters, completed/player-row validation, patch/date/tier filtering, post-filter count, partial-record handling, examined/hydrated coverage, and limit-specific truncation in src/open_dota_mcp/services/fantasy.py
- [X] T017 [US1] Implement the additive `fantasy_scoring` projection with exactly 18 pre-modifier entries, nullable raw points, and reference URI while exposing no historical quality, trait, title, banner, or loadout fields in src/open_dota_mcp/services/fantasy.py
- [X] T018 [US1] Register the read-only idempotent `get_pro_player_fantasy` tool with the complete fixed traversal budgets, bounded-response, selector, filter, unavailable-stat, group, professional-only, truncation, and error description in src/open_dota_mcp/server.py

**Checkpoint**: US1 independently returns analysis-ready professional-map evidence and optional pre-modifier scores without admitting public or unverified matches.

---

## Phase 4: User Story 4 - Resolve a Team's Latest Observed Lineup (Priority: P1)

**Goal**: Resolve one professional team to exactly five cross-checked account IDs from its newest usable parsed match and infer only positions supported by clean lane and ten-minute-farm evidence.

**Independent Test**: Feed team histories with newer unparsed/malformed maps, a usable lineup within five completed records, exact and mismatched current-member sets, and clean/ambiguous lanes; verify the newest usable selection, fixed scan bound, cannot-infer outcomes, and correct/null positions.

### Tests for User Story 4

- [X] T019 [P] [US4] Add public roster model and risk-based mapping tests for selector validation, strict current-member booleans, requested-team side verification, exact five-player sets, latest valid ten-minute samples, clean 2-1-2 inference, tied/missing/malformed evidence, deterministic ordering, and coverage bounds in tests/unit/test_roster_mapping.py
- [X] T020 [P] [US4] Add MCP contract tests for ID/name resolution, ten-candidate ambiguity, fixed five-record scan, exact membership equality, `current_roster_unavailable`, immediate `lineup_mismatch`, `lineup_unavailable`, retry/partial failures, slim bounded output, and tool description/annotations in tests/contract/test_roster_tool.py
- [X] T021 [P] [US4] Add an offline team-to-player-to-fantasy journey proving five fantasy-ready IDs, no older scan after mismatch, and no unsupported positions in tests/integration/test_roster_to_fantasy.py

### Implementation for User Story 4

- [X] T022 [US4] Implement fully typed and Google-documented roster request, team/source/coverage, candidate, lineup-player, warning, and structured outcome models in src/open_dota_mcp/models/roster.py
- [X] T023 [US4] Implement team resolution reuse, concurrent current-member/history loading, newest-first sequential five-record scan, verified team-side extraction, immediate set-mismatch failure, professional-name enrichment, conservative position inference, and sparse warnings in src/open_dota_mcp/services/roster.py
- [X] T024 [US4] Register the read-only idempotent `get_pro_team_roster` tool with fixed-scan, current-member cross-check, latest-observed provenance, nullable position, bounded-response, and error documentation in src/open_dota_mcp/server.py

**Checkpoint**: US4 independently returns exactly five safe player IDs or a bounded cannot-infer outcome and never calls the result an authoritative current roster.

---

## Phase 5: User Story 2 - Understand TI 2026 Scoring and Modifiers (Priority: P2)

**Goal**: Expose an installed, network-free JSON MCP resource containing the frozen TI 2026 formulas, five multipliers, modifier inventory, aggregation, provenance, caveats, and edition metadata.

**Independent Test**: List and read the resource outside the repository cwd with network access disabled; verify all 18 formulas, five exact tiers, frozen trait/title inventory, evidence/source rules, unknown-effect nullability, aggregation, and exact scorer parity.

### Tests for User Story 2

- [X] T025 [P] [US2] Add schema, canonical formula/input/color parity, source resolution, edition metadata, five-tier multiplier, retrospective modifier order/scope/prerequisite rules, frozen trait/title inventory, unknown-numeric rejection, projection labeling, and aggregation invariant tests in tests/unit/test_fantasy_models.py
- [X] T026 [P] [US2] Add in-memory resource listing/reading tests for stable URI, name, JSON MIME type, annotations, retrospective projection semantics, installed-package loading outside cwd, deterministic content, and zero network requests in tests/contract/test_fantasy_tool.py

### Implementation for User Story 2

- [X] T027 [US2] Create the installed `ti-2026-v1` scoring document with 18 emblems, five quality tiers, five traits, eight prefixes, eight suffixes, retrospective application order/scope/prerequisites, counterfactual-projection semantics, aggregation, evidence statuses, direct sources, dates, and caveats in src/open_dota_mcp/resources/ti_2026_fantasy.json
- [X] T028 [US2] Implement typed scoring-reference validation for formula parity, known operation/input mappings, internal source IDs, HTTPS links, inventory completeness, retrospective projection semantics, and null numeric effects for unknown facts in src/open_dota_mcp/fantasy_rules.py
- [X] T029 [US2] Add package-relative `importlib.resources` loading and register `opendota://fantasy/ti-2026/scoring` as a read-only idempotent `application/json` resource in src/open_dota_mcp/resources/__init__.py and src/open_dota_mcp/server.py

**Checkpoint**: US2 independently supplies complete, versioned scoring context without a live rules search or network request.

---

## Phase 6: User Story 3 - Evaluate Stat Combinations in Series Context (Priority: P3)

**Goal**: Ensure an agent can apply candidate emblem configurations retrospectively to historical evidence and compare counterfactual projections across trustworthy series while preserving unknown grouping and rule uncertainty.

**Independent Test**: Run the fixed 20-case agent-evaluation corpus across at least two players and two candidate emblem configurations; require at least 18 expected comparisons, correct two-best-maps/best-confirmed-series aggregation, preserved null-series evidence, and no representation of candidate configurations as historical facts.

### Tests for User Story 3

- [X] T030 [P] [US3] Add a fixed parameterized corpus of 20 offline agent-evaluation cases covering at least two players, two candidate emblem configurations, known/null series IDs, unavailable statistics, and known/unknown modifiers; require at least 18 expected comparisons with correct evidence selection, raw and projected scores, two-best-maps/best-confirmed-series aggregation, uncertainty, and no historical-loadout claims in tests/integration/test_fantasy_journey.py

### Implementation for User Story 3

- [X] T031 [US3] Finalize trustworthy upstream-only series preservation and enforce the separation between observed historical evidence/pre-modifier scores and agent-selected counterfactual configurations in src/open_dota_mcp/services/fantasy.py
- [X] T032 [P] [US3] Document retrospective candidate-configuration projection, two-best-maps/best-confirmed-series analysis, null-series limitation, paired-banner contribution, pre-modifier evidence boundary, projection labeling, and no-optimizer scope in README.md

**Checkpoint**: US3 can be performed entirely from the two MCP capabilities while uncertainty remains explicit.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Complete shared fixtures, user documentation, protocol validation, and the independent release gate.

- [X] T033 [P] Consolidate reusable fantasy, roster, resource, clock, no-sleep retry, and no-network fixtures without hiding expected values in tests/conftest.py
- [X] T034 [P] Extend stdio discovery and invocation coverage to six tools and one resource while asserting protocol-only stdout and actionable structured errors in tests/integration/test_stdio.py
- [X] T035 [P] Document both new tools, the scoring resource, slim defaults, focused selectors/filters, `fantasy_scoring`, fixed 500-history/200-detail and post-filter bounds, limit-specific truncation metadata, terminal exhaustion, retrospective projection semantics, professional-only eligibility, and optional API-key secrecy in README.md
- [X] T036 Execute every offline validation journey including the 20-case/18-pass retrospective evaluation corpus and correct any command, expected behavior, or bounded-response documentation mismatch in specs/004-ti-2026-fantasy/quickstart.md
- [X] T037 Have a sub-agent that performed no implementation audit all required public-surface and risk-based tests, then run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`, requiring it to report all gates passing before completion in specs/004-ti-2026-fantasy/tasks.md
- [X] T038 Add regression coverage and allow an explicit `version_pattern` to operate with an undated OpenDota patch catalog in tests/contract/test_fantasy_tool.py and src/open_dota_mcp/services/fantasy.py
- [X] T039 Add regression coverage for OpenDota's nullable integer First Blood flags and map them to reliable true/false fantasy evidence in tests/unit/test_fantasy_mapping.py, tests/contract/test_fantasy_tool.py, and src/open_dota_mcp/services/fantasy.py

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; begins immediately.
- **Foundational (Phase 2)**: Depends on T001 and blocks every user story.
- **US1 (Phase 3)**: Depends on Phase 2; produces the MVP player-evidence capability.
- **US4 (Phase 4)**: Depends on Phase 2 and can run in parallel with US1; its end-to-end bridge test uses the completed US1 tool.
- **US2 (Phase 5)**: Depends on T013 for canonical formula definitions but is otherwise independently readable and testable.
- **US3 (Phase 6)**: Depends on completed US1 and US2 surfaces because it validates their combined workflow.
- **Polish (Phase 7)**: Depends on all stories selected for delivery; T037 is always last.

### User Story Dependency Graph

```text
Setup -> Foundation -> US1 (P1/MVP) ---------+
                    -> US4 (P1)              +-> US3 (P3) -> Polish -> Independent QA
                    -> US2 (P2, after T013) --+
```

### Within Each User Story

- Write the listed public-surface and risk-based tests before or alongside implementation.
- Implement typed models and canonical rules before services.
- Implement mapping and validation before collection/orchestration.
- Register MCP surfaces only after their model/service behavior exists.
- Run the story's independent test at its checkpoint before proceeding.

## Parallel Opportunities

- T002 and T003 can be authored together; after those tests exist, T004, T005, and T006 touch independent source files.
- T007 through T011 cover separate US1 test surfaces and can be authored in parallel.
- T019 through T021 cover separate US4 unit, contract, and integration surfaces and can be authored in parallel.
- Once Foundation completes, US1 and the US4 model/service path can proceed in parallel; T021 waits for the US1 tool.
- T025 and T026 can be authored in parallel, and the JSON work in T027 can proceed independently of resource registration until parity validation.
- T030 and T032 touch different US3 files and can proceed in parallel after US1 and US2.
- T033, T034, and T035 touch different cross-cutting files and can proceed in parallel before quickstart and independent QA.

## Parallel Example: User Story 1

```text
Task T007: Add public fantasy model and formula tests in tests/unit/test_fantasy_models.py
Task T008: Add raw-stat and Tormentor mapping tests in tests/unit/test_fantasy_mapping.py
Task T009: Add professional-player resolution tests in tests/unit/test_identity_resolution.py
Task T010: Add MCP contract tests in tests/contract/test_fantasy_tool.py
Task T011: Add the offline player journey in tests/integration/test_fantasy_journey.py
```

## Parallel Example: User Story 4

```text
Task T019: Add roster model and mapping tests in tests/unit/test_roster_mapping.py
Task T020: Add roster MCP contract tests in tests/contract/test_roster_tool.py
Task T021: Add the team-to-fantasy integration journey in tests/integration/test_roster_to_fantasy.py
```

## Parallel Example: User Story 2

```text
Task T025: Add scoring-reference schema and parity tests in tests/unit/test_fantasy_models.py
Task T026: Add MCP resource discovery/read tests in tests/contract/test_fantasy_tool.py
Task T027: Transcribe the frozen evidence inventory in src/open_dota_mcp/resources/ti_2026_fantasy.json
```

## Parallel Example: User Story 3

```text
Task T030: Add the combined series/scoring journey in tests/integration/test_fantasy_journey.py
Task T032: Document the series-context workflow in README.md
```

## Implementation Strategy

### MVP First: User Story 1

1. Complete T001-T006 for fixtures and shared OpenDota/cache support.
2. Complete T007-T018 for the professional-only player evidence tool.
3. Run the US1 unit, contract, and integration checkpoint independently.
4. Stop here for an MVP that returns bounded analysis-ready maps and raw scores.

### Incremental Delivery

1. Deliver Setup + Foundation.
2. Deliver US1 as the player-evidence MVP.
3. Deliver US4 as the focused team-to-five-player bridge.
4. Deliver US2 as the offline scoring/modifier reference.
5. Deliver US3 as the verified combined series-analysis workflow.
6. Complete cross-cutting protocol/docs work and require independent QA.

### Agent Execution Guidance

1. Preserve existing user changes and complete tasks in ID order unless a `[P]` opportunity is explicitly used.
2. Keep tests deterministic and offline; use explicit fixtures, `httpx.MockTransport`, temporary cache stores, and injected no-sleep retry controls.
3. Do not add public pagination to either new tool: the roster result is fixed at five players and fantasy evidence is a caller-bounded 1-100 collection. Expose coverage, truncation, and terminal exhaustion metadata instead.
4. Do not research or invent new TI 2026 rules during implementation; serialize the frozen planning inventory and preserve unknowns.
5. Do not complete T037 until an independent non-implementing sub-agent reports Ruff lint, Ruff format, and the full pytest suite passing.

## Notes

- `[P]` tasks change distinct files or independent test surfaces after their stated prerequisites.
- Story labels provide traceability to the specification even though US4 is scheduled before US2 and US3 due to its P1 priority.
- Commit after a task or cohesive logical group; the configured git hooks remain optional.
- Preserve null, zero, and false as separate meanings and fail closed on professional provenance and lineup membership.
