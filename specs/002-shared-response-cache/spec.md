# Feature Specification: Shared OpenDota Response Cache

**Feature Branch**: `002-shared-response-cache`

**Created**: 2026-07-25

**Status**: Draft

**Input**: User description: "Cache OpenDota responses across local MCP process and computer restarts, using a 15-minute default lifetime and an explicitly assigned 1-day lifetime for stable data, with bounded storage and cache-usage visibility. Preserve the existing process-local pagination cache."

## Clarifications

### Session 2026-07-25

- Q: What should happen when a new OpenDota MCP version encounters still-unexpired entries written in an incompatible cache format? → A: Cache only upstream OpenDota content, assume MCP upgrades remain compatible, and provide a full-cache removal command as fallback.
- Q: If the single coordinated upstream request fails after its retry budget is exhausted, what should happen to other callers waiting for that same cache key? → A: All waiting callers receive the same final failure; a later request may retry.
- Q: What protection should be required for cached data stored on disk? → A: Restrict access to the current operating-system user; no cache-specific encryption.
- Q: How should full-cache removal behave when MCP processes are still running? → A: Clear safely, ignore writes from older in-flight requests, and allow later requests to repopulate.
- Q: Should pagination snapshots and continuation tokens move into persistent shared storage with the response cache? → A: No. Keep the existing process-local pagination cache behavior; cross-process pagination does not justify persistence or rebuilding every next page from raw JSON.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reuse Responses Across MCP Instances (Priority: P1)

As an agent using the local OpenDota MCP server, I want equivalent requests to reuse a still-valid response even when the agent harness has stopped or replaced the MCP process, so that ordinary session and response lifecycles do not consume scarce unauthenticated OpenDota calls unnecessarily.

**Why this priority**: Avoiding repeated upstream calls is the primary value of the feature and directly addresses unauthenticated call limits.

**Independent Test**: Make an OpenDota-backed request, stop that MCP process, start another local instance, and repeat the equivalent request before expiry. The second instance returns the same response without another upstream call.

**Acceptance Scenarios**:

1. **Given** no valid cached response exists, **When** an agent makes an OpenDota-backed request, **Then** the system obtains the response from OpenDota, returns it, and makes it available for reuse by other local MCP instances.
2. **Given** a valid cached response exists, **When** the same or another local MCP instance makes an equivalent request, **Then** the system returns the cached response without calling OpenDota.
3. **Given** a valid cached response was stored before all MCP processes stopped, **When** a new agent session starts a new MCP process, **Then** that process can reuse the response for the remainder of its original validity period.
4. **Given** a valid cached response was stored before the computer restarted, **When** an MCP process starts after restart, **Then** it can reuse the response for the remainder of its original validity period.
5. **Given** several local MCP instances concurrently request the same uncached information, **When** the first upstream request is in progress, **Then** the instances coordinate so that no more than one successful upstream fetch is needed to populate the shared response.

---

### User Story 2 - Apply Appropriate Freshness Lifetimes (Priority: P2)

As an agent, I want changing data to refresh promptly while stable data remains reusable longer, so that answers balance freshness with protection from OpenDota call limits.

**Why this priority**: Shared storage only saves calls safely when each kind of information has a clear, predictable freshness policy.

**Independent Test**: Exercise an unclassified endpoint, declared stable reference data, a parsed match, and an unparsed match; verify that each response receives the specified category and becomes unavailable for reuse at the correct expiry time.

**Acceptance Scenarios**:

1. **Given** an OpenDota-backed request has no explicit long-lived classification, **When** its response is cached, **Then** it is short-lived and expires 15 minutes after it was stored.
2. **Given** a request retrieves explicitly classified stable information such as heroes or patch numbers, **When** its response is cached, **Then** it is long-lived and expires 1 day after it was stored.
3. **Given** a match-specific response confirms the match is parsed, **When** that response is cached, **Then** it is long-lived and expires 1 day after it was stored.
4. **Given** a match-specific response is unparsed or its parsed status cannot be confirmed, **When** that response is cached, **Then** it is short-lived and expires 15 minutes after it was stored.
5. **Given** a cached response has expired, **When** an equivalent request arrives, **Then** the expired response is not returned and the request is refreshed from OpenDota.

---

### User Story 3 - Preserve Existing Pagination Behavior (Priority: P3)

As an agent paging through a large result set, I want the current in-memory snapshot behavior to remain unchanged, so that each continuation reads already-transformed snapshot records without repeatedly rebuilding pages from cached raw OpenDota JSON.

**Why this priority**: Pagination is already bounded and fit for a local MCP process. Preserving it avoids added persistence complexity and repeated transformation work for a cross-process scenario that is unlikely in this project.

**Independent Test**: Exercise a multi-page traversal and verify the existing 30-minute, 32-snapshot process-local registry, immutable transformed records, rotating single-use tokens, and process-restart invalidation remain unchanged after the response cache is introduced.

**Acceptance Scenarios**:

1. **Given** a nonterminal first page, **When** the same MCP process requests the next page, **Then** it reads the already-normalized and filtered records held by the existing process-local snapshot rather than reconstructing them from raw cached responses.
2. **Given** an active pagination snapshot, **When** 30 minutes elapse, the 32-snapshot capacity is exceeded, or the owning MCP process stops, **Then** the continuation becomes unavailable and the agent receives the existing recoverable restart guidance.
3. **Given** the shared response cache is cleared, unavailable, or evicts a response, **When** an already-materialized process-local pagination snapshot is continued, **Then** its traversal behavior remains independent of the response-cache lifecycle.

---

### User Story 4 - Inspect Cache Use and Capacity (Priority: P4)

As a local operator, I want to see cache effectiveness and storage use, so that I can verify the feature is reducing OpenDota calls and diagnose unexpected cache behavior.

**Why this priority**: Visibility makes the feature operable and demonstrates whether it is delivering its intended value without requiring a larger administration interface.

**Independent Test**: Generate cache hits, misses, expiry, and eviction, then use the local inspection interface to verify that aggregate and per-entry usage information reflects those events.

**Acceptance Scenarios**:

1. **Given** cached requests have occurred, **When** the operator requests a cache summary, **Then** the system shows entry count, total storage used, configured maximum size, hits, misses, writes, expirations, and evictions.
2. **Given** the operator requests entry details, **When** entries exist, **Then** the system shows a safe key description, freshness category, creation and expiry times, stored size, last-use time, and reuse count for each listed entry.
3. **Given** request credentials or other secrets influence an upstream call, **When** cache information is inspected, **Then** those secrets are not displayed.
4. **Given** the operator determines that cached content is unusable, **When** the operator invokes full-cache removal and confirms the action, **Then** all cached responses and response-cache usage metadata are removed together, even if MCP processes remain active; independent process-local pagination snapshots are unchanged.
5. **Given** full-cache removal completes while upstream requests are already in flight, **When** those older requests finish, **Then** their results do not repopulate the cache; requests begun after removal may populate it normally.

### Edge Cases

- The computer clock changes after an entry is stored; validity remains based on the entry's absolute expiry and an entry is never extended merely by a clock adjustment or process restart.
- Two MCP instances attempt to write the same response concurrently; readers receive one complete response and never a partial or corrupted value.
- An MCP process stops while writing; later processes detect and discard incomplete data without losing unrelated valid entries.
- The shared cache is unavailable, unwritable, or corrupt; normal requests remain usable through OpenDota when possible, and operators receive actionable diagnostics rather than malformed cached data.
- An upstream request fails; the failure itself is not cached as a successful response, and an expired response is not silently represented as fresh.
- A coordinated population exhausts its retry budget; every caller already waiting for that cache identity receives that same final failure, while a later request begins a new coordinated attempt.
- A response is larger than the entire configured capacity; it is returned to the caller but not retained, and existing unrelated entries are not all discarded to accommodate it.
- Storage is full of entries currently in use by other MCP instances; cleanup does not remove an entry while it is being read or written.
- Semantically equivalent requests express parameters in a different order; they map to the same cache identity, while requests that can produce different response content remain distinct.
- A new GET query parameter is added without cache-specific classification; it is treated as content-altering and changes the cache identity automatically. Only a parameter on the explicit reviewed non-content-altering exclusion list, initially API-key authentication material, may be omitted.
- A previously long-lived match response reports an unparsed game due to inconsistent upstream data; unconfirmed or unparsed data receives the safer short-lived classification.
- An MCP software upgrade occurs while entries remain valid; the entries remain eligible for reuse because cached response content follows the OpenDota contract rather than an MCP response representation.
- Full-cache removal races with active readers and writers; existing callers complete safely, no work started before the removal restores cleared data, and work started afterward sees the new empty-cache generation.
- A continuation is used after its MCP process was replaced; the existing process-local registry returns recoverable restart guidance rather than attempting cross-process restoration.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST check for a valid cached response before every cache-eligible OpenDota request and MUST call OpenDota only when no valid response is available.
- **FR-002**: Cached responses MUST be shared by all OpenDota MCP processes running for the same local user on the same computer; their availability MUST NOT depend on the lifetime of an MCP process, agent response, conversation, or harness session.
- **FR-003**: Cached responses MUST remain available across a computer restart until their originally assigned expiry time or capacity-based eviction.
- **FR-004**: The system MUST assign the short-lived category to every cacheable response unless that response is explicitly covered by a long-lived classification.
- **FR-005**: Short-lived entries MUST expire 15 minutes after successful storage, and cache reuse MUST NOT extend that expiry.
- **FR-006**: Long-lived entries MUST expire 1 day after successful storage, and cache reuse MUST NOT extend that expiry.
- **FR-007**: The long-lived classification MUST explicitly include stable reference information for heroes and patch numbers and MUST allow other endpoints to be added only through an explicit, reviewable classification.
- **FR-008**: Match-specific information MUST be long-lived only when the returned information confirms that the match is parsed; unparsed or unconfirmed match information MUST remain short-lived.
- **FR-009**: The system MUST define cache identity from the OpenDota API contract, operation, source/base path, path inputs, and the complete structured query-parameter mapping used to build the upstream GET URL. Every path and query parameter MUST be presumed content-altering and included by default, so an unclassified future parameter changes the identity automatically; semantically equivalent mappings MUST be canonicalized.
- **FR-010**: The system MUST cache upstream OpenDota response content rather than MCP-shaped responses; caller-specific MCP response shaping MUST occur after either cached or newly fetched upstream content is obtained.
- **FR-011**: Existing pagination pages and continuation state MUST remain in the process-local pagination cache with its existing transformed snapshot representation, 30-minute lifetime, 32-traversal capacity, least-recently-used eviction, and rotating single-use token behavior.
- **FR-012**: Shared response-cache persistence, capacity accounting, inspection, and clear operations MUST NOT store, enumerate, expire, evict, or remove pagination snapshots or continuation tokens.
- **FR-013**: Concurrent local instances requesting an identical missing or expired entry MUST share one coordinated population attempt, including its bounded upstream retries; all waiting callers MUST receive the same completed response or the same final failure after retry exhaustion, and only a later request may begin a new coordinated attempt.
- **FR-014**: The cache MUST have a configurable maximum on-disk size with a default of 1 GiB per local user.
- **FR-015**: When space is required, the system MUST remove expired entries first and then the least recently used eligible entries until the cache is within its configured maximum; in-use and incomplete entries MUST be handled without exposing partial content.
- **FR-016**: A response larger than the configured maximum MUST be returned but MUST NOT be cached.
- **FR-017**: The system MUST provide a local command-line inspection and management interface that works independently of a running MCP process.
- **FR-018**: The inspection interface MUST report aggregate entry count, stored size, maximum size, hits, misses, successful writes, expirations, evictions, and requests bypassed because the cache was unavailable.
- **FR-019**: The inspection interface MUST provide per-entry safe key description, category, creation time, expiry time, stored size, last-use time, and reuse count, with bounded output and optional filtering so large caches do not produce unbounded results.
- **FR-020**: Usage counters and entry metadata MUST be shared and persistent across MCP processes and computer restarts, subject to the same capacity management as the responses they describe.
- **FR-021**: The system MUST never return an expired, incomplete, unreadable, or corrupt entry as a valid response.
- **FR-022**: If the cache cannot be read or written, the system MUST continue with the normal OpenDota request when possible, record or emit actionable diagnostics, and avoid turning a cache failure into a false successful response.
- **FR-023**: Unsuccessful OpenDota outcomes MUST NOT be retained as successful cached responses.
- **FR-024**: Cache diagnostics and inspection output MUST NOT expose OpenDota credentials, authentication material, or raw sensitive request values.
- **FR-025**: Cache behavior MUST be identical for Codex-started MCP processes and other standards-compliant local MCP harnesses; no caller may need to keep a particular server process alive to retain cache validity.
- **FR-026**: A new OpenDota MCP software version MUST continue to use unexpired entries without invalidating them solely because the MCP version changed.
- **FR-027**: The local management interface MUST provide an explicitly confirmed operation that safely removes the entire shared response cache, including cached responses and usage metadata, without requiring active MCP processes to stop; results from work started before the completed removal MUST NOT repopulate the cache, while requests started afterward MAY populate it normally, and process-local pagination state MUST remain outside this operation.
- **FR-028**: Cache data and management operations MUST be accessible only to the operating-system user who owns the cache; cache-specific encryption at rest is not required.
- **FR-029**: A GET query parameter MAY be omitted from cache identity only when it appears in an explicit, narrowly scoped, code-reviewed non-content-altering exclusion list. The initial exclusion is API-key authentication material. Each addition MUST verify the upstream contract and add regression tests proving the deliberate equivalence; credentials and other excluded values MUST NOT appear in stored identities, safe descriptions, diagnostics, or inspection output.

### Key Entities

- **Cache Entry**: Successfully obtained upstream OpenDota response content associated with a canonical request identity, freshness category, creation and absolute expiry times, stored size, last-use time, reuse count, and integrity state; it is independent of MCP response shaping.
- **Cache Identity**: A secret-safe, canonical representation of the upstream operation and all URL-building path/query inputs, with every GET parameter treated as content-altering unless explicitly reviewed onto the non-content-altering exclusion list; MCP response shaping and continuation state are excluded.
- **Freshness Classification**: The policy assigning an entry to short-lived (default, 15 minutes) or long-lived (explicit, 1 day), including conditional classification for parsed matches.
- **Pagination Snapshot**: Existing process-local traversal state containing normalized, filtered match summaries and opaque continuation metadata; it is deliberately independent of the shared response cache.
- **Usage Summary**: Persistent aggregate counters and capacity information used by the local operator to evaluate cache effectiveness and health.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In lifecycle tests covering a stopped MCP process, a new harness session, and a computer restart simulation, 100% of unexpired, non-evicted test entries are reusable without an additional OpenDota call.
- **SC-002**: Across classification tests, 100% of unclassified and unparsed responses expire after 15 minutes, while 100% of explicitly stable and confirmed parsed-match responses expire after 1 day, with no reuse extending either lifetime.
- **SC-003**: For 20 simultaneous equivalent requests across multiple local MCP instances, no more than one successful OpenDota call is made to populate the shared response.
- **SC-004**: After any capacity-management operation, stored cache data remains at or below the configured maximum, and 100% of retained entries remain complete and readable.
- **SC-005**: An operator can obtain cache effectiveness and capacity information in one command in under 2 seconds for a cache containing 10,000 entries on a typical development computer.
- **SC-006**: In inspection tests, reported hits, misses, writes, expirations, and evictions match generated events exactly, and no supplied credential appears in keys, diagnostics, or displayed metadata.
- **SC-007**: In fault tests covering unavailable storage, interrupted writes, and corrupt entries, 100% of requests either obtain a fresh OpenDota response or return a clear upstream/cache diagnostic; none return partial or corrupt cached content.
- **SC-008**: Existing pagination regression tests remain unchanged and pass for 30-minute expiry, 32-snapshot capacity, immutable transformed records, token rotation/replay rejection, and restart-required behavior after process replacement.
- **SC-009**: In MCP upgrade compatibility tests, 100% of unexpired response entries remain reusable when the OpenDota request contract is unchanged, and a confirmed full-cache removal leaves zero cached responses or prior response-cache usage counters without changing live process-local pagination snapshots.
- **SC-010**: For 20 simultaneous equivalent requests whose coordinated upstream attempt exhausts its retry budget, all 20 callers receive the same final failure and no caller begins an independent upstream attempt; the next later request begins one new coordinated attempt.
- **SC-011**: In supported-platform access-control tests, another non-privileged operating-system user cannot read, modify, inspect, or clear the cache owned by the test user.
- **SC-012**: In a full-cache removal test with 20 active readers or writers, the operation completes without partial reads or process shutdowns, leaves zero prior entries or counters, rejects every write initiated before completion, and permits requests initiated afterward to populate normally.
- **SC-013**: Identity tests show that adding or changing any unclassified GET query parameter changes the cache digest, parameter ordering does not, API-key-only changes do not, and no excluded credential appears in identity or inspection representations.

## Assumptions

- Version one provides a command-line inspection experience rather than a web interface, consistent with the project's local developer audience and smallest-useful-surface principle.
- The default maximum cache size is 1 GiB per local user and can be adjusted for machines with different storage constraints.
- Cache scope is one operating-system user on one computer; sharing across user accounts or computers is out of scope.
- Only successful, cache-eligible read responses are retained. Mutating operations, if introduced later, require an explicit cache invalidation design before becoming cache eligible.
- Entries expire at a fixed time calculated when successfully stored; this feature does not provide sliding expiration or serve stale data after expiry.
- Existing MCP response shaping, pagination boundaries, retry budgets, caller deadlines, and cancellation behavior remain authoritative. Cache lookup and population must preserve those caller-visible contracts.
- Cross-process pagination and persistent continuation tokens are out of scope. The response cache does not replace or unify the existing process-local pagination cache because doing so would add persistence primarily for an unlikely local-MCP process handoff and could require repeated transformation of raw JSON on each page.
- OpenDota remains the source of truth, and endpoint classifications will be reviewed alongside official OpenDota documentation when the implementation plan identifies the complete endpoint inventory.
- MCP software upgrades are assumed not to affect cache usability because stored response content is tied to the OpenDota API contract; full-cache removal is the recovery path for exceptional incompatibility.
- Cached OpenDota data is public upstream information stored as local application data; operating-system per-user access controls are sufficient, and cache-specific encryption is out of scope.
