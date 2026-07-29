# Tasks: Shared OpenDota Response Cache

**Input**: Design documents from `/specs/002-shared-response-cache/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cache-interface.md`, `quickstart.md`

**Tests**: pytest coverage is required for every new public cache/CLI function and for all three existing MCP tools at the cache boundary. Risk-based internal tests cover identity canonicalization, SQLite integrity/capacity, cross-process coordination, fixed expiry, generation-safe clear, permissions, and pagination isolation. All tests must be deterministic and offline.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated as an independent increment after the shared foundation is complete.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it changes different files and has no dependency on another incomplete task in the same phase
- **[Story]**: Maps the task to a user story in `spec.md`
- Every task names the exact file or files it changes or validates

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the cache package and deterministic test support without changing runtime behavior.

- [X] T001 Create the typed cache package exports and module boundaries described by the plan in `src/open_dota_mcp/cache/__init__.py`
- [X] T002 [P] Add temporary owner-only cache directories, mutable wall clocks, deterministic polling jitter, and SQLite test helpers in `tests/conftest.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Provide validated per-user configuration and the transactional schema required by every story.

**Critical**: No user-story implementation begins until this phase is complete.

- [X] T003 [P] Add public `Settings.from_env()` and `Settings.validate()` tests for platform cache paths, `OPENDOTA_CACHE_DIR`, the positive retained main-database `OPENDOTA_CACHE_MAX_BYTES` value, secret-free errors, and unchanged retry/snapshot defaults in `tests/unit/test_config.py`
- [X] T004 Extend the typed runtime settings with a resolved user cache directory and default 1 GiB retained main-database maximum while rejecting invalid or secret-bearing configuration in `src/open_dota_mcp/config.py`
- [X] T005 [P] Add schema/bootstrap tests for Cache Control, Response Entry, Usage Summary, Active Population, and Population Outcome records, full auto-vacuum, page bounds, finite busy timeout, rollback journaling, schema versioning, and atomic interrupted initialization in `tests/unit/test_cache_store.py`
- [X] T006 Implement typed SQLite records, connection/bootstrap transactions, schema indexes, off-event-loop operation support, and owner-only `0700` directory/`0600` database creation in `src/open_dota_mcp/cache/store.py`

**Checkpoint**: A validated, owner-only, bounded SQLite store can be initialized without network access; all user stories may now proceed.

---

## Phase 3: User Story 1 - Reuse Responses Across MCP Instances (Priority: P1) MVP

**Goal**: Store complete successful upstream JSON below MCP shaping and reuse it across process, harness, and simulated computer restarts while coordinating equivalent concurrent misses.

**Independent Test**: Make an eligible request through one client process, close it, open a replacement process on the same database, and repeat the equivalent request before expiry; the second response must match without a second mocked OpenDota call. Twenty concurrent equivalent misses must share one successful fetch or one exhausted failure.

### Tests for User Story 1

- [X] T007 [P] [US1] Add deterministic cache-identity tests for typed canonical mappings, reordered equivalence, base path/operation/path/query distinctions, fail-closed unknown query parameters, the reviewed `api_key` exclusion, rejected non-finite values, bounded safe descriptions, and absence of credentials/package/session data in `tests/unit/test_cache_identity.py`
- [X] T008 [P] [US1] Add response-entry tests for atomic complete-JSON writes, digest/length/JSON verification, hit/miss/write counters, fixed metadata, corruption rejection, and no successful storage of malformed or failed upstream outcomes in `tests/unit/test_cache_store.py`
- [X] T009 [P] [US1] Extend typed-client tests for all nine operations to prove every unclassified cacheable result receives the mandatory 900-second fallback, cache hits and fresh payloads share top-level validation/MCP shaping, query identity uses the complete HTTP parameter mapping, credentials stay excluded, cancellation propagates, and existing safe retry classification, bounded increasing jitter, valid/invalid `Retry-After`, recovery, and exhaustion remain deterministic in `tests/unit/test_opendota_client.py`
- [X] T010 [P] [US1] Add 20-process coordinated-success, coordinated-retry-exhaustion, later-new-attempt, waiter-cancellation, and owner-crash/lease-expiry acceptance tests with no real sleeps in `tests/integration/test_cache_multiprocess.py`

### Implementation for User Story 1

- [X] T011 [US1] Implement canonical OpenDota contract identities, default inclusion of every GET path/query input, the centralized reviewed `api_key` exclusion, SHA-256 digests, source normalization, and bounded secret-safe descriptions in `src/open_dota_mcp/cache/identity.py`
- [X] T012 [US1] Implement atomic response lookup/write that requires a resolved category and immutable expiry, integrity verification, exact transactional counters, corrupt/expired miss handling, and complete upstream JSON serialization in `src/open_dota_mcp/cache/store.py`
- [X] T013 [US1] Implement generation-bound population lease election/renewal/release and short-lived sanitized terminal outcomes so waiters share one success or final failure without holding SQLite locks across I/O in `src/open_dota_mcp/cache/store.py`
- [X] T014 [US1] Implement the mandatory typed 900-second fallback for every unclassified cacheable result in `src/open_dota_mcp/cache/policy.py`, then integrate cache identity, lookup, coordinated ownership/waiting, existing bounded retry execution, resolved category/expiry, and successful raw JSON storage into every typed GET operation before object/list validation in `src/open_dota_mcp/clients/opendota.py`; no response may be stored without an immutable expiry
- [X] T015 [US1] Add fresh-to-hit, replacement-process, replacement-harness, restart/reopen, compatible-version reuse, unavailable-write fresh return, and identical hit/miss shaping acceptance coverage in `tests/integration/test_cache_lifecycle.py`
- [X] T016 [US1] Extend all three MCP contract suites to prove unchanged slim defaults, every draft include group, invalid selections, focused selectors/filters, 20/100 page bounds, structured upstream failures, and identical cached/fresh results in `tests/contract/test_draft_tool.py`, `tests/contract/test_tournament_tool.py`, and `tests/contract/test_team_tool.py`

**Checkpoint**: User Story 1 independently demonstrates durable reuse and single coordinated population without changing the published MCP schemas.

---

## Phase 4: User Story 2 - Apply Appropriate Freshness Lifetimes (Priority: P2)

**Goal**: Apply a fixed 15-minute default and a fixed 1-day lifetime only to heroes, patches, and confirmed parsed matches, never extending expiry on reuse.

**Independent Test**: Store an unclassified response, heroes, patches, a parsed match, and each unparsed/unconfirmed match variant under an injected clock; verify category, exact absolute expiry, boundary expiration, and refresh behavior.

### Tests for User Story 2

- [X] T017 [P] [US2] Add classifier tests for 900-second default, explicit 86,400-second heroes/patches, positive non-boolean match `version`, and missing/null/boolean/nonpositive/malformed match versions in `tests/unit/test_cache_policy.py`
- [X] T018 [P] [US2] Add fixed-expiry store tests for `now < expires_at`, equality expiration, immutable stored timestamps, no sliding extension on hits, forward/backward wall-clock observations, expiration counters, and expired-first cleanup in `tests/unit/test_cache_store.py`

### Implementation for User Story 2

- [X] T019 [US2] Extend the typed freshness policy with explicitly reviewed 86,400-second classifications for heroes, patches, and confirmed parsed matches while retaining the mandatory short-lived fallback for every other result in `src/open_dota_mcp/cache/policy.py`
- [X] T020 [US2] Extend post-decode integration to apply category-specific classification and immutable UTC `created_at`/`expires_at` values during response insertion and expiration cleanup in `src/open_dota_mcp/cache/store.py` and `src/open_dota_mcp/clients/opendota.py`
- [X] T021 [US2] Add lifecycle acceptance tests for all freshness categories, exact expiry boundaries, refresh after expiration, failed refresh without stale serving, and unchanged expiry across process/restart simulations in `tests/integration/test_cache_lifecycle.py`

**Checkpoint**: User Story 2 independently proves every cacheable operation receives the safe default or an explicit reviewed long lifetime.

---

## Phase 5: User Story 3 - Preserve Existing Pagination Behavior (Priority: P3)

**Goal**: Keep transformed continuation snapshots process-local, immutable, bounded to 32 traversals for 30 minutes, and independent of response-cache persistence, eviction, and clearing.

**Independent Test**: Traverse multiple pages, clear or evict the underlying response cache, and continue from the already-materialized snapshot without re-decoding raw JSON or rerunning transformations; expiry, LRU eviction, token replay, and process replacement must retain existing restart guidance.

### Tests for User Story 3

- [X] T022 [P] [US3] Extend registry unit tests for immutable transformed records, 30-minute fixed expiry, 32-traversal LRU, rotating single-use tokens, tool/query binding, replay rejection, and replacement-process invalidation in `tests/unit/test_pagination.py`
- [X] T023 [P] [US3] Add tournament/team contract regressions proving continuation uses materialized summaries, retains 20/100 bounds and terminal metadata, and remains valid after response-cache eviction or clear in `tests/contract/test_tournament_tool.py` and `tests/contract/test_team_tool.py`

### Implementation for User Story 3

- [X] T024 [US3] Wire the shared response cache only into the default `OpenDotaClient` while preserving an independently constructed process-local `SnapshotRegistry` and protocol-only three-tool server surface in `src/open_dota_mcp/server.py`
- [X] T025 [US3] Add lifecycle coverage proving no pagination tables/counters/inspection rows exist, continuations perform no raw-payload rehydration, clear leaves active snapshots untouched, and restart guidance remains recoverable in `tests/integration/test_cache_lifecycle.py`

**Checkpoint**: User Story 3 independently confirms the persistent response cache has not changed pagination representation or lifecycle.

---

## Phase 6: User Story 4 - Inspect Cache Use and Capacity (Priority: P4)

**Goal**: Bound retained SQLite allocation, expose fast secret-safe cache information and bounded entry pages from a standalone CLI, and safely clear live caches with generation protection.

**Independent Test**: Generate exact hits, misses, writes, expirations, evictions, bypasses, and filtered entry pages; inspect them from a separate CLI process, then run confirmed clear during active work and verify old work cannot repopulate while pagination remains untouched.

### Tests for User Story 4

- [X] T026 [P] [US4] Add capacity tests for the configured retained main-database page bound, explicit exclusion of temporary transaction files, expired-first then deterministic LRU eviction, active/incomplete record protection, oversized-response bypass without unrelated eviction, rollback on failed capacity work, and retained-record readability in `tests/unit/test_cache_store.py`
- [X] T027 [P] [US4] Add public CLI contract tests for human/JSON `info` with allocated/stored main-database bytes and the configured retained maximum, 50-default/500-maximum filtered `entries`, deterministic seek cursors and terminal pages, invalid filters/limits/cursors, exact counters, safe descriptions, confirmation-required clear, exit statuses, and credential/raw-payload exclusion in `tests/contract/test_cache_cli.py`
- [X] T028 [P] [US4] Add console/module subprocess tests for no-argument protocol-only stdio plus standalone `cache info`, `cache entries`, and `cache clear --yes` dispatch with stdout/stderr separation in `tests/integration/test_stdio.py`
- [X] T029 [P] [US4] Add live-process clear tests for active readers/writers, generation changes, pre-clear waiter handling, old completion rejection, post-clear repopulation, zeroed counters, and unchanged pagination in `tests/integration/test_cache_multiprocess.py`
- [X] T030 [P] [US4] Add cache-unavailable, lock-timeout, corrupt/unsupported database, symlink, wrong-owner, restrictive-mode, secret-safe diagnostic, bypass-counter, and normal-upstream-fallback tests in `tests/integration/test_cache_lifecycle.py`

### Implementation for User Story 4

- [X] T031 [US4] Implement retained main-database allocated-size enforcement using `page_count × page_size`, oversized preflight, expired-first and deterministic LRU transactional eviction, rollback on insufficient space, and exact capacity/counter snapshots in `src/open_dota_mcp/cache/store.py`
- [X] T032 [US4] Implement fully typed and Google-documented `info` with allocated/stored main-database bytes and the configured retained maximum, bounded/filterable seek-paginated `entries`, opaque cursors, and confirmed generation-safe `clear` APIs with secret-safe result models in `src/open_dota_mcp/cache/store.py`
- [X] T033 [US4] Implement the human/JSON `cache info`, `cache entries`, and `cache clear --yes` argument parsing, bounded rendering, validation, diagnostics, and exit behavior in `src/open_dota_mcp/cache/cli.py`
- [X] T034 [US4] Preserve no-argument stdio startup while dispatching only explicit cache management subcommands for both installed and module entry points in `src/open_dota_mcp/__main__.py`
- [X] T035 [US4] Add a deterministic 10,000-entry `cache info` benchmark in `tests/contract/test_cache_cli.py`: on the existing `offline-quality` x64 Linux CI baseline of at least 2 vCPU, 8 GiB RAM, 14 GiB local SSD storage, and Python 3.13, run one unmeasured warm-up followed by five measured invocations using a monotonic clock, exclude fixture/database-population time, assert the median duration is under 2.0 seconds, and retain the 500-row output-bound assertion

**Checkpoint**: User Story 4 independently provides bounded, fast, credential-safe inspection and race-safe full removal without an MCP administration tool.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Synchronize operator guidance and run feature-wide interoperability and quality gates.

- [X] T036 [P] Document cache location/capacity environment variables, fixed freshness categories, bounded inspection commands, confirmed removal, failure fallback, pagination separation, and secret-handling guidance in `README.md` and `.env.example`
- [X] T037 [P] Review every new public function/class for complete type signatures and Google-style docstrings and keep cache diagnostics off protocol stdout in `src/open_dota_mcp/cache/`, `src/open_dota_mcp/config.py`, `src/open_dota_mcp/clients/opendota.py`, and `src/open_dota_mcp/__main__.py`
- [X] T038 Run the complete offline scenarios and Codex-compatible protocol inspection from `specs/002-shared-response-cache/quickstart.md`, including all contract/integration tests and `uv run fastmcp inspect src/open_dota_mcp/server.py:mcp`
- [X] T039 Require a non-implementing QA sub-agent to audit constitution-required public-surface and risk-based tests, then pass `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest` for the repository paths in `src/`, `tests/`, and `pyproject.toml`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks every user story.
- **US1 (Phase 3)**: Depends only on Foundational; this is the MVP and supplies the shared lookup/population path.
- **US2 (Phase 4)**: T017-T018 may be developed against the store/client contracts after Foundational; T019 depends on the mandatory short-lived policy established by T014, and T020-T021 depend on T012/T014/T019.
- **US3 (Phase 5)**: T022-T023 may run after Foundational, but T024-T025 depend on T014 so final server wiring and lifecycle validation use the completed shared client boundary.
- **US4 (Phase 6)**: T026-T028 and T030 may be developed after Foundational against the relevant contracts, but T029 and T031-T034 depend on T012-T014 as applicable for live coordination, storage, and dispatch integration.
- **Polish (Phase 7)**: Depends on every story selected for release. T039 is always the final implementation gate.

### User Story Dependency Graph

```text
Setup -> Foundational -> US1 (MVP with mandatory short-lived fallback)
                           -> US2 --extends freshness policy and insertion
                           -> US3 --validates pagination isolation and server wiring
                           -> US4 --extends shared store with capacity/operations
US1 + US2 + US3 + US4 -> Polish -> Independent QA
```

### Within Each User Story

- Write or update the required public-surface and risk-based tests before or alongside implementation.
- Implement identity/policy/store primitives before wiring the HTTP client, server, or CLI.
- Keep SQLite transactions short and never hold them across HTTP I/O, retry sleeps, or MCP shaping.
- Complete the independent test at the checkpoint before treating the story as deliverable.

## Parallel Opportunities

- T001 and T002 can proceed independently.
- T003 and T005 can be authored in parallel after Setup; T004 and T006 then satisfy their contracts.
- In US1, T007-T010 touch distinct test surfaces and can run in parallel before T011-T014.
- US2 classifier tests (T017) and expiry storage tests (T018) can proceed independently; T019 then extends T014's fallback policy before T020 integrates category-specific expiry.
- US3 unit/contract regressions (T022/T023) can proceed independently.
- In US4, T026-T030 cover distinct store, CLI, stdio, multiprocess, and fault surfaces and can be authored concurrently before T031-T034.
- Documentation/type review (T036/T037) can proceed in parallel after behavior stabilizes; T038 and T039 remain sequential release gates.

## Parallel Example: User Story 1

```text
Task T007: Canonical and secret-safe cache identity tests in tests/unit/test_cache_identity.py
Task T008: Response entry integrity and counter tests in tests/unit/test_cache_store.py
Task T009: Typed client cache/retry boundary tests in tests/unit/test_opendota_client.py
Task T010: Twenty-process coordination tests in tests/integration/test_cache_multiprocess.py
```

## Parallel Example: User Story 2

```text
Task T017: Freshness classifier tests in tests/unit/test_cache_policy.py
Task T018: Fixed-expiry storage tests in tests/unit/test_cache_store.py
```

## Parallel Example: User Story 3

```text
Task T022: SnapshotRegistry regression tests in tests/unit/test_pagination.py
Task T023: Tournament/team continuation contract tests in tests/contract/
```

## Parallel Example: User Story 4

```text
Task T026: Capacity and eviction tests in tests/unit/test_cache_store.py
Task T027: Bounded management contract tests in tests/contract/test_cache_cli.py
Task T028: Entry-point/stdout tests in tests/integration/test_stdio.py
Task T029: Live-clear concurrency tests in tests/integration/test_cache_multiprocess.py
Task T030: Permissions and cache-bypass tests in tests/integration/test_cache_lifecycle.py
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundational phases.
2. Complete T007-T016 for durable reuse, coordinated population, and the mandatory 15-minute fallback for every unclassified cacheable result.
3. Run the US1 independent lifecycle and 20-process tests.
4. Validate all three MCP contracts remain unchanged.
5. Stop here for an MVP demonstration if freshness differentiation, pagination regression certification, and operator CLI are not yet required for the delivery.

### Incremental Delivery

1. **Foundation**: Owner-only SQLite schema plus validated cache configuration.
2. **US1 MVP**: Durable raw-response reuse and cross-process single population.
3. **US2**: Explicit fixed freshness categories and expiry behavior.
4. **US3**: Certified preservation of process-local pagination semantics.
5. **US4**: Bounded capacity, inspection, diagnostics, and generation-safe clear.
6. **Release gate**: Documentation, quickstart validation, and independent QA.

## Notes

- `[P]` means different files or isolated test surfaces with no incomplete dependency; tasks that modify `store.py` are intentionally sequenced.
- Existing MCP response shaping remains applicable and unchanged: slim defaults, cohesive draft include groups, focused team/tournament selectors, bounded 20/100 pagination, continuation metadata, and terminal pages are regression-tested in T016/T023.
- The management CLI uses bounded 50/500 entry pages because MCP response shaping is inapplicable to an operator-only interface that must work without a running server.
- Failures and coordination outcomes are never successful cached responses; no expired response is served stale.
- T039 cannot pass until an independent sub-agent that performed no implementation completes the required audit and quality commands.
