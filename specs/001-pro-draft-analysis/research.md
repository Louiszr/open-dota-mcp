# Phase 0 Research: Professional Draft Analysis MCP

## Official OpenDota surface

**Decision**: Build against OpenDota OpenAPI 31.1.0 at `https://api.opendota.com/api` and isolate all upstream shapes in one typed asynchronous client.

**Rationale**: The official contract documents unauthenticated operation with an optional API key, plus the exact read endpoints needed by the feature. `GET /matches/{match_id}` exposes draft actions (`picks_bans`), draft timing, players, teams, league, patch, scores, duration, and parse version. `/leagues` and `/leagues/{league_id}/matches` support professional tournament resolution/discovery; `/teams?page=N` (zero-indexed, up to 1,000 entries per page), `/teams/{team_id}`, and `/teams/{team_id}/matches` support team resolution/discovery. `/heroes`, `/constants/patch`, and `/proPlayers` provide authoritative labels. The league/team match endpoints document no caller pagination inputs, so MCP pagination cannot be delegated upstream.

**Alternatives considered**: `/proMatches` was rejected as the primary tournament source because it is a global recent feed and cannot guarantee complete traversal of an arbitrary league. `/leagues/{id}/matchIds` was rejected because it includes amateur leagues and lacks the compact discovery context. OpenDota Explorer/SQL was rejected as overly broad and outside the documented feature surface.

## Framework and structured MCP responses

**Decision**: Use current FastMCP typed async tools, Pydantic response models, generated output schemas, the in-memory FastMCP client for most protocol tests, and stdio as the runtime/default subprocess integration transport.

**Rationale**: FastMCP derives complete tool schemas from annotated signatures, supports async I/O, emits standard structured content from typed object results, and provides in-memory and stdio clients for compatibility tests. Domain results use typed sparse unions whose diagnostics carry stable non-OK status and codes so agents can branch without routine success markers; unexpected failures use masked MCP errors. The server reserves stdout for protocol messages and uses framework logging/stderr for diagnostics.

**Alternatives considered**: Hand-writing JSON-RPC/MCP transport was rejected because it duplicates standards work. Returning only JSON text was rejected because it loses output-schema validation and structured-content ergonomics. HTTP transport was rejected because the feature is local, single-user, and explicitly compatible with stdio clients.

## HTTP client and retry policy

**Decision**: Use one `httpx.AsyncClient`; retry safe GET requests for HTTP 429, 408, 500, 502, 503, and 504 plus eligible connect/read timeout and connection failures. Permit three total attempts, at most 10 seconds of cumulative retry delay, and exponential delay starting at 250 ms with jitter and a 5-second per-delay cap. Parse both delta-seconds and HTTP-date `Retry-After`; honor it only when valid and within the remaining retry and request budget. Propagate cancellation immediately.

**Rationale**: Every operation is read-only and repeatable. Finite attempt, delay, and timeout budgets satisfy the constitution while preventing retry storms. `asyncio.CancelledError` must never be wrapped or retried, allowing MCP client cancellation/deadline enforcement to stop HTTP work and pending delays. Tests inject a sleeper, clock, and deterministic jitter source so recovery and exhaustion have no real delay.

**Alternatives considered**: A third-party retry package was rejected because the policy is small and domain-specific. Unbounded `Retry-After` sleeping and retrying all 4xx responses were rejected as unsafe. Fixed delays were rejected because bounded exponential jitter reduces synchronized retry pressure.

## Deterministic snapshot pagination

**Decision**: Materialize each first-page tournament/team result set into a 30-minute process-local traversal snapshot and issue rotating opaque random continuation tokens. Store only normalized match summaries, the canonical query fingerprint, page size, and offset; discard state at the terminal page or expiry.

**Rationale**: The upstream league/team endpoints expose no continuation contract, while the feature requires no repeated/skipped match and excludes newly completed games from an active traversal. A short-lived server-side snapshot provides those semantics without persistent storage and keeps tokens concise. Thirty minutes is sufficient for a local agent to traverse pages but bounded enough to clean abandoned state. Expired or post-restart tokens fail explicitly with restart guidance.

**Alternatives considered**: Offset pagination over refetched upstream results can skip/repeat records after mutation. A stateless keyset token excludes newer matches but cannot preserve a true snapshot if older records are inserted or corrected. Embedding every match ID in a signed token makes tokens grow without bound. Persistent storage conflicts with the feature's local, no-persistence scope.

## Draft ordering and player association

**Decision**: Treat a draft of `n` actions as authoritative only when its order values are exactly `0..n-1`; otherwise preserve upstream array sequence and expose `source_index`, nullable supplied `order`, and `ordering_quality: degraded`. Associate a pick only to a unique same-side player with the same hero ID. Prefer the match player professional `name`, then the pro-player catalog `name`, then an explicit Steam32 account-ID fallback; never read `personaname` for display. Confirm a requested draft is professional by membership in `/leagues/{league_id}/matches`, whose documented purpose excludes amateur leagues.

**Rationale**: The official match schema describes each pick/ban's `is_pick`, `hero_id`, `team`, and `order`, and player records contain `hero_id`, side/slot, `account_id`, professional `name`, and Steam `personaname`. Unique same-side hero matching is deterministic. Exact zero-based coverage detects missing leading, internal, duplicate, and out-of-range order values. Professional-league membership uses an explicit documented OpenDota classification rather than a local heuristic.

**Alternatives considered**: Sorting partially valid order values could silently manufacture chronology. Matching by hero without side can produce ambiguity. Using Steam persona names violates the requested professional identity semantics. Inferring identities or missing actions from other matches was rejected as unauthoritative.

## Name resolution

**Decision**: Normalize by Unicode case folding, converting punctuation/spacing runs to one separator, and comparing normalized league names or team names/tags. Return a unique exact match; otherwise rank normalized substring matches deterministically and return at most 10 candidates.

**Rationale**: This handles harmless case, punctuation, and spacing variation while remaining explainable. Stable numeric IDs remain authoritative, and team candidates include tag and last-match recency to distinguish renamed/reused labels.

**Alternatives considered**: Typo-tolerant edit-distance/fuzzy matching was rejected because the spec explicitly excludes it. Automatically choosing the highest-ranked substring was rejected because ambiguous selection must remain caller-controlled.

## Agent-context protection

**Decision**: Keep discovery records as a fixed slim domain projection and page them at 20 by default/100 maximum. Keep the required draft core always present and expose only `competition`, `result`, `draft_timing`, and `provenance` as validated additive groups.

**Rationale**: Discovery records are already the minimum information needed to choose a match, so another field selector would add complexity without material savings. Draft timing and provenance can be verbose and are separable from the primary ordered-draft scenario. Unknown upstream fields are ignored.

**Alternatives considered**: Returning raw OpenDota records was rejected as unstable and context-heavy. Arbitrary field selection was rejected because it weakens compatibility and validation. Pagination for draft actions was rejected because the 10-match request bound and naturally small professional draft make the cohesive per-match record more usable.

## Sparse diagnostics and duplicate inputs

**Decision**: Silently collapse duplicate requested match IDs at their first occurrence and expose no `duplicates_omitted` field or equivalent diagnostic. Successful responses and records omit generic `status`, empty `warnings`, and absent `error` fields. Every emitted warning or error is non-empty and carries the machine-actionable non-OK `status` inside the diagnostic object; ambiguity uses a warning with `status: needs_selection`, while failures put their outcome status inside `error`.

**Rationale**: Duplicate inputs do not change the requested domain result and therefore do not justify response noise. Sparse diagnostics reduce routine payload size and let the presence of `warnings` or `error` signal that attention is required. Nesting non-OK status with its code and explanation keeps the state and cause inseparable while retaining structured branching for agents. Domain state such as `completeness`, `ordering_quality`, and pagination `terminal` remains explicit because it is not a generic success diagnostic.

**Alternatives considered**: Retaining `status: ok`, empty arrays, null errors, and `duplicates_omitted: []` was rejected as repetitive context overhead. A top-level non-OK status plus a separate diagnostic was rejected because it duplicates state and can become inconsistent. Omitting all status values was rejected because ambiguity and failure callers still need a stable machine-readable outcome.
